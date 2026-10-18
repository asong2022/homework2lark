#!/usr/bin/env python3
"""Resumable Agent intake for a small batch of homework images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import intake  # noqa: E402

INPUT_VERSION = "intake-batch-v1"
STATE_VERSION = "intake-batch-state-v1"
MIN_ITEMS = 1
MAX_ITEMS = 20
SUPPORTED_MODES = frozenset(("single", "chat"))
PERSISTED_STATUSES = frozenset(("pending", "created", "failed"))

JSONValue = intake.JSONValue
JSONWriter = Callable[[Path, Mapping[str, JSONValue]], None]


@dataclass(frozen=True)
class BatchItem:
    item_code: str
    path: Path
    file_name: str
    sha256: str
    size: int


@dataclass(frozen=True)
class BatchInput:
    mode: str
    items: tuple[BatchItem, ...]
    digest: str


def _object(value: JSONValue, label: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise intake.SkillError("invalid_batch", f"{label} 必须是对象。")
    return value


def _load_json(path: Path, *, code: str, message: str) -> dict[str, JSONValue]:
    try:
        decoded: JSONValue = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise intake.SkillError(code, message) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise intake.SkillError(code, message) from None
    if not isinstance(decoded, dict):
        raise intake.SkillError(code, message)
    return decoded


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise intake.SkillError("input_unreadable", "批量收题中有图片无法读取。") from None
    return digest.hexdigest()


def _input_digest(mode: str, items: Sequence[BatchItem]) -> str:
    projection = {
        "mode": mode,
        "items": [
            {
                "itemCode": item.item_code,
                "fileName": item.file_name,
                "sha256": item.sha256,
                "size": item.size,
                "pathFingerprint": hashlib.sha256(
                    os.path.normcase(os.path.normpath(str(item.path))).encode("utf-8")
                ).hexdigest(),
            }
            for item in items
        ],
    }
    encoded = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_batch_input(path: Path) -> BatchInput:
    input_path = path.expanduser().resolve()
    raw = _load_json(
        input_path,
        code="input_unreadable",
        message="无法读取批量收题清单。",
    )
    if set(raw) != {"schemaVersion", "mode", "items"}:
        raise intake.SkillError("invalid_batch", "批量收题清单字段不完整或包含未知字段。")
    if raw.get("schemaVersion") != INPUT_VERSION:
        raise intake.SkillError("invalid_batch", f"schemaVersion 必须是 {INPUT_VERSION}。")
    mode = raw.get("mode")
    if not isinstance(mode, str) or mode not in SUPPORTED_MODES:
        raise intake.SkillError("invalid_batch", "mode 必须是 single 或 chat。")
    raw_items = raw.get("items")
    if not isinstance(raw_items, list) or not MIN_ITEMS <= len(raw_items) <= MAX_ITEMS:
        raise intake.SkillError("invalid_batch", "items 必须包含 1～20 张图片。")

    items: list[BatchItem] = []
    for index, value in enumerate(raw_items, start=1):
        if not isinstance(value, dict) or set(value) != {"itemCode", "path"}:
            raise intake.SkillError(
                "invalid_batch",
                "每个批量项目必须且只能包含 itemCode 和 path。",
            )
        expected_code = f"I{index:02d}"
        if value.get("itemCode") != expected_code:
            raise intake.SkillError("invalid_batch", "itemCode 必须从 I01 连续排列。")
        raw_path = value.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise intake.SkillError("invalid_batch", "path 必须是非空图片路径。")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = input_path.parent / candidate
        resolved = candidate.resolve()
        intake.IntakeService._validate_image(resolved)
        try:
            size = resolved.stat().st_size
        except OSError:
            raise intake.SkillError("input_unreadable", "批量收题中有图片无法读取。") from None
        items.append(
            BatchItem(
                item_code=expected_code,
                path=resolved,
                file_name=resolved.name,
                sha256=_sha256(resolved),
                size=size,
            )
        )
    normalized_mode = str(mode)
    return BatchInput(normalized_mode, tuple(items), _input_digest(normalized_mode, items))


def atomic_write_json(path: Path, value: Mapping[str, JSONValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_or_fail(
    writer: JSONWriter,
    path: Path,
    value: Mapping[str, JSONValue],
    *,
    code: str,
    message: str,
) -> None:
    try:
        writer(path, value)
    except OSError:
        raise intake.SkillError(code, message, retryable=True) from None


def _new_state(batch: BatchInput, state_path: Path) -> dict[str, JSONValue]:
    namespace = hashlib.sha256(
        f"{os.path.normcase(str(state_path))}:{batch.digest}".encode()
    ).hexdigest()[:32]
    return {
        "schemaVersion": STATE_VERSION,
        "mode": batch.mode,
        "inputDigest": batch.digest,
        "sessionNamespace": namespace,
        "items": [
            {
                "itemCode": item.item_code,
                "fileName": item.file_name,
                "sha256": item.sha256,
                "size": item.size,
                "status": "pending",
            }
            for item in batch.items
        ],
    }


def _session_relative_path(item_code: str, namespace: str) -> str:
    return f"sessions/{namespace}/{item_code}.json"


def _load_session(path: Path, *, mode: str, file_name: str) -> dict[str, JSONValue]:
    session = _load_json(path, code="invalid_state", message="项目会话文件缺失或损坏。")
    source = session.get("source")
    if (
        session.get("schemaVersion") != intake.SESSION_VERSION
        or session.get("mode") != mode
        or not isinstance(source, dict)
        or source.get("fileName") != file_name
    ):
        raise intake.SkillError("invalid_state", "项目会话文件与批量输入不一致。")
    try:
        _problem_ids(session, mode)
    except intake.SkillError:
        raise intake.SkillError("invalid_state", "项目会话中的题目 ID 无效。") from None
    return session


def _validate_error(value: JSONValue) -> dict[str, JSONValue]:
    if not isinstance(value, dict) or set(value) != {"code", "retryable"}:
        raise intake.SkillError("invalid_state", "批量状态中的错误摘要已损坏。")
    if not isinstance(value.get("code"), str) or not value["code"]:
        raise intake.SkillError("invalid_state", "批量状态中的错误码无效。")
    if not isinstance(value.get("retryable"), bool):
        raise intake.SkillError("invalid_state", "批量状态中的重试标记无效。")
    return value


def _validate_state_shape(state: dict[str, JSONValue], state_path: Path) -> None:
    if set(state) != {"schemaVersion", "mode", "inputDigest", "sessionNamespace", "items"}:
        raise intake.SkillError("invalid_state", "批量状态字段不完整或包含未知字段。")
    mode = state.get("mode")
    if (
        state.get("schemaVersion") != STATE_VERSION
        or not isinstance(mode, str)
        or mode not in SUPPORTED_MODES
    ):
        raise intake.SkillError("invalid_state", "批量状态版本或模式无效。")
    digest = state.get("inputDigest")
    if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        raise intake.SkillError("invalid_state", "批量状态摘要无效。")
    namespace = state.get("sessionNamespace")
    if not isinstance(namespace, str) or re.fullmatch(r"[a-f0-9]{32}", namespace) is None:
        raise intake.SkillError("invalid_state", "批量会话命名空间无效。")
    raw_items = state.get("items")
    if not isinstance(raw_items, list) or not MIN_ITEMS <= len(raw_items) <= MAX_ITEMS:
        raise intake.SkillError("invalid_state", "批量状态项目数量无效。")

    for index, value in enumerate(raw_items, start=1):
        if not isinstance(value, dict):
            raise intake.SkillError("invalid_state", "批量状态项目结构无效。")
        expected_code = f"I{index:02d}"
        base_keys = {"itemCode", "fileName", "sha256", "size", "status"}
        status = value.get("status")
        if (
            value.get("itemCode") != expected_code
            or not isinstance(status, str)
            or status not in PERSISTED_STATUSES
        ):
            raise intake.SkillError("invalid_state", "批量状态项目编号或状态无效。")
        if (
            not isinstance(value.get("fileName"), str)
            or Path(str(value["fileName"])).name != value["fileName"]
        ):
            raise intake.SkillError("invalid_state", "批量状态文件名无效。")
        if not isinstance(value.get("sha256"), str) or len(str(value["sha256"])) != 64:
            raise intake.SkillError("invalid_state", "批量状态图片摘要无效。")
        if (
            not isinstance(value.get("size"), int)
            or isinstance(value.get("size"), bool)
            or value["size"] < 0
        ):
            raise intake.SkillError("invalid_state", "批量状态图片大小无效。")

        if status == "created":
            if set(value) != base_keys | {"problemIds", "sessionFile"}:
                raise intake.SkillError("invalid_state", "已创建项目的批量状态无效。")
            problem_ids = value.get("problemIds")
            if not isinstance(problem_ids, list) or not all(
                isinstance(problem_id, str) and problem_id for problem_id in problem_ids
            ):
                raise intake.SkillError("invalid_state", "批量状态中的题目 ID 无效。")
            expected_session = _session_relative_path(expected_code, namespace)
            if value.get("sessionFile") != expected_session:
                raise intake.SkillError("invalid_state", "批量状态中的会话文件无效。")
            session_path = state_path.parent / expected_session
            session = _load_session(session_path, mode=mode, file_name=str(value["fileName"]))
            if _problem_ids(session, mode) != problem_ids:
                raise intake.SkillError("invalid_state", "批量状态与会话中的题目 ID 不一致。")
        elif status == "failed":
            error = _validate_error(value.get("error"))
            expected_keys = base_keys | {"error"}
            if error["code"] == "session_write_failed":
                expected_keys |= {"sourceAssetId", "problemIds"}
                if not isinstance(value.get("sourceAssetId"), str) or not value["sourceAssetId"]:
                    raise intake.SkillError("invalid_state", "无法恢复已创建项目的来源 ID。")
                ids = value.get("problemIds")
                if (
                    not isinstance(ids, list)
                    or any(not isinstance(item, str) or not item for item in ids)
                    or (mode == "single" and len(ids) != 1)
                    or (mode == "chat" and ids)
                ):
                    raise intake.SkillError("invalid_state", "无法恢复已创建项目的题目 ID。")
            if set(value) != expected_keys:
                raise intake.SkillError("invalid_state", "失败项目的批量状态无效。")
        elif set(value) != base_keys:
            raise intake.SkillError("invalid_state", "待处理项目的批量状态无效。")


def _assert_matches_input(state: dict[str, JSONValue], batch: BatchInput) -> None:
    if state.get("mode") != batch.mode or state.get("inputDigest") != batch.digest:
        raise intake.SkillError("input_conflict", "批量输入已改变，不能复用原状态文件。")
    raw_items = state.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != len(batch.items):
        raise intake.SkillError("input_conflict", "批量输入项目与原状态不一致。")
    for state_item, input_item in zip(raw_items, batch.items, strict=True):
        if not isinstance(state_item, dict):
            raise intake.SkillError("invalid_state", "批量状态项目结构无效。")
        expected = (
            input_item.item_code,
            input_item.file_name,
            input_item.sha256,
            input_item.size,
        )
        actual = (
            state_item.get("itemCode"),
            state_item.get("fileName"),
            state_item.get("sha256"),
            state_item.get("size"),
        )
        if actual != expected:
            raise intake.SkillError("input_conflict", "批量输入图片与原状态不一致。")


def _problem_ids(manifest: dict[str, JSONValue], mode: str) -> list[str]:
    if mode == "chat":
        return []
    raw = manifest.get("problems")
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise intake.SkillError("api_invalid_response", "单题批量收题没有返回唯一题目。")
    problem_id = raw[0].get("problemId")
    if not isinstance(problem_id, str) or not problem_id:
        raise intake.SkillError("api_invalid_response", "单题批量收题缺少题目 ID。")
    return [problem_id]


def _public_item(
    value: dict[str, JSONValue],
    *,
    mode: str,
    outcome: str | None = None,
) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {
        "itemCode": value["itemCode"],
        "status": value["status"],
    }
    if outcome is not None:
        result["outcome"] = outcome
    if value["status"] == "created":
        problem_ids = value["problemIds"]
        if mode == "single":
            if not isinstance(problem_ids, list) or len(problem_ids) != 1:
                raise intake.SkillError("invalid_state", "单题批量状态必须包含唯一题目 ID。")
            result["problemId"] = problem_ids[0]
        result["sessionFile"] = value["sessionFile"]
    elif value["status"] == "failed":
        result["error"] = value["error"]
        if "sourceAssetId" in value:
            result["assetId"] = value["sourceAssetId"]
            if mode == "single":
                result["problemId"] = value["problemIds"][0]
    return result


def _summary(
    state: dict[str, JSONValue],
    *,
    outcomes: Mapping[str, str] | None = None,
) -> dict[str, JSONValue]:
    raw_items = state["items"]
    if not isinstance(raw_items, list):
        raise intake.SkillError("invalid_state", "批量状态项目无效。")
    items = [
        _public_item(
            value,
            mode=str(state["mode"]),
            outcome=outcomes.get(str(value["itemCode"])) if outcomes is not None else None,
        )
        for value in raw_items
        if isinstance(value, dict)
    ]
    return {
        "mode": state["mode"],
        "created": sum(item["status"] == "created" for item in items),
        "failed": sum(item["status"] == "failed" for item in items),
        "pending": sum(item["status"] == "pending" for item in items),
        "noChange": sum(item.get("outcome") == "no_change" for item in items),
        "items": items,
    }


class BatchIntakeService:
    def __init__(
        self,
        intake_service: intake.IntakeService,
        *,
        writer: JSONWriter = atomic_write_json,
    ) -> None:
        self.intake_service = intake_service
        self.writer = writer

    def start(self, input_path: Path, state_path: Path) -> dict[str, JSONValue]:
        batch = load_batch_input(input_path)
        state_path = state_path.expanduser().resolve()
        if state_path.exists():
            state = _load_json(
                state_path,
                code="invalid_state",
                message="批量状态文件无法读取或已经损坏。",
            )
            _validate_state_shape(state, state_path)
            _assert_matches_input(state, batch)
        else:
            state = _new_state(batch, state_path)
            _write_or_fail(
                self.writer,
                state_path,
                state,
                code="state_write_failed",
                message="无法安全创建批量状态文件。",
            )

        raw_items = state["items"]
        if not isinstance(raw_items, list):
            raise intake.SkillError("invalid_state", "批量状态项目无效。")
        outcomes: dict[str, str] = {}
        for input_item, state_value in zip(batch.items, raw_items, strict=True):
            if not isinstance(state_value, dict):
                raise intake.SkillError("invalid_state", "批量状态项目结构无效。")
            if state_value["status"] == "created":
                outcomes[input_item.item_code] = "no_change"
                continue
            session_relative = _session_relative_path(
                input_item.item_code, str(state["sessionNamespace"])
            )
            session_path = state_path.parent / session_relative
            recovered = session_path.exists()
            if recovered:
                session = _load_session(
                    session_path, mode=batch.mode, file_name=input_item.file_name
                )
            elif (
                isinstance(state_value.get("error"), dict)
                and state_value["error"].get("code") == "session_write_failed"
            ):
                raise intake.SkillError(
                    "session_recovery_required",
                    "本项已在服务端创建。请用 status 取得原题目 ID 并修复会话，不能再次上传。",
                )
            try:
                if not recovered:
                    session = self.intake_service.start(input_item.path, batch.mode)
                problem_ids = _problem_ids(session, batch.mode)
                try:
                    if not recovered:
                        self.writer(session_path, session)
                except OSError:
                    state_value.clear()
                    state_value.update(
                        {
                            "itemCode": input_item.item_code,
                            "fileName": input_item.file_name,
                            "sha256": input_item.sha256,
                            "size": input_item.size,
                            "status": "failed",
                            "error": {"code": "session_write_failed", "retryable": False},
                            "sourceAssetId": session["source"]["assetId"],
                            "problemIds": problem_ids,
                        }
                    )
                    _write_or_fail(
                        self.writer,
                        state_path,
                        state,
                        code="state_write_failed",
                        message="会话文件失败后，批量状态也无法安全落盘。",
                    )
                    raise intake.SkillError(
                        "session_write_failed",
                        "题目已由本地服务接收，但会话文件无法安全落盘；本批次已停止。",
                        retryable=False,
                    ) from None
                state_value.clear()
                state_value.update(
                    {
                        "itemCode": input_item.item_code,
                        "fileName": input_item.file_name,
                        "sha256": input_item.sha256,
                        "size": input_item.size,
                        "status": "created",
                        "problemIds": problem_ids,
                        "sessionFile": session_relative,
                    }
                )
                outcome = "no_change" if recovered else "created"
            except intake.SkillError as exc:
                if exc.code in {"session_write_failed", "state_write_failed"}:
                    raise
                state_value.clear()
                state_value.update(
                    {
                        "itemCode": input_item.item_code,
                        "fileName": input_item.file_name,
                        "sha256": input_item.sha256,
                        "size": input_item.size,
                        "status": "failed",
                        "error": {"code": exc.code, "retryable": exc.retryable},
                    }
                )
                outcome = "failed"

            _write_or_fail(
                self.writer,
                state_path,
                state,
                code="state_write_failed",
                message="批量进度无法安全落盘，本批次已停止。",
            )
            outcomes[input_item.item_code] = outcome
        return _summary(state, outcomes=outcomes)


def status(state_path: Path) -> dict[str, JSONValue]:
    resolved = state_path.expanduser().resolve()
    state = _load_json(
        resolved,
        code="invalid_state",
        message="批量状态文件无法读取或已经损坏。",
    )
    _validate_state_shape(state, resolved)
    return _summary(state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default=os.environ.get("SHI_HOMEWORK2LARK_API_URL", intake.DEFAULT_API_URL),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--input", required=True)
    start.add_argument("--state", required=True)
    show = commands.add_parser("status")
    show.add_argument("--state", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    intake._force_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            service = BatchIntakeService(intake.IntakeService(intake.HttpGateway(args.api_url)))
            result = service.start(Path(args.input), Path(args.state))
        else:
            result = status(Path(args.state))
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except intake.SkillError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "retryable": exc.retryable,
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
