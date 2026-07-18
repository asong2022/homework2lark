#!/usr/bin/env python3
"""Map observed returned-practice answers back to immutable worksheet manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import practice_sheet  # noqa: E402

PLAN_VERSION = "retry-feedback-plan-v1"
EVENT_VERSION = "retry-feedback-event-v1"
RESULTS = frozenset(("correct", "partial", "incorrect", "uncertain", "not_observed"))
MASTERY_OPTIONS = frozenset(("未开始", "练习中", "需再练", "已掌握"))
PAGE_CODE = re.compile(
    r"^(?P<batch>\d{8}-(?:0[1-9]|[1-9]\d))(?P<instance>-S\d{3})?-P(?P<page>[1-9]\d*)$"
)


class RetryBatchError(ValueError):
    """Raised when returned-practice evidence cannot be mapped safely."""


@dataclass(frozen=True)
class RetryEvent:
    batch_code: str
    instance_code: str | None
    page_number: int
    item_code: str
    question_id: str
    variant_id: str | None
    student_name: str | None
    student_number: str | None
    observed_response: str
    mark_evidence: str
    result: str
    teacher_judgment: str
    mastery: str | None
    observed_at: str

    @property
    def event_id(self) -> str:
        # 事件身份 = 批次、匿名实例、页码、Rxx、来源、观察事实、教师判断和时间。
        # 姓名/学号不参与哈希：Sxxx 才是稳定身份，名单更正姓名不得让同一
        # 事件生成新 ID 而追加重复行（retry-feedback.md 合约）。
        identity = {
            key: value
            for key, value in asdict(self).items()
            if key not in ("student_name", "student_number")
        }
        encoded = json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "retry_" + hashlib.sha256(encoded).hexdigest()[:24]

    def private(self) -> dict[str, Any]:
        return {"eventId": self.event_id, **asdict(self)}

    def base_projection(self) -> dict[str, Any]:
        if self.result == "correct":
            summary = "本次再练作答正确，继续观察稳定性。"
        elif self.result == "partial":
            summary = "本次再练部分正确，仍需针对未完成环节继续练习。"
        elif self.result == "incorrect":
            summary = "本次再练仍有错误，需要继续针对原有问题练习。"
        elif self.result == "uncertain":
            summary = "本次再练证据不清晰，需人工查看原稿。"
        else:
            summary = "本次再练未观察到有效作答。"
        return {
            "eventId": self.event_id,
            "questionId": self.question_id,
            "variantId": self.variant_id,
            "studentName": self.student_name,
            "result": self.result,
            "mastery": self.mastery,
            "summary": summary,
            "needsHuman": self.result in {"uncertain", "not_observed"},
        }


@dataclass(frozen=True)
class ManifestEntry:
    manifest: practice_sheet.PracticeManifest
    path: Path

    @property
    def key(self) -> tuple[str, str | None]:
        student = self.manifest.student
        return (
            self.manifest.batch_code,
            student.instance_code if student is not None else None,
        )


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RetryBatchError(f"无法读取{label} JSON。") from exc


def _text(value: object, label: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise RetryBatchError(f"{label} 必须是文本。")
    normalized = value.strip()
    if required and not normalized:
        raise RetryBatchError(f"{label} 不能为空。")
    if len(normalized) > maximum:
        raise RetryBatchError(f"{label} 过长。")
    return normalized


def _parse_time(value: object) -> str:
    observed_at = _text(value, "observedAt", 50)
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetryBatchError("observedAt 必须是 ISO 8601 时间。") from exc
    if parsed.tzinfo is None:
        raise RetryBatchError("observedAt 必须包含时区。")
    return observed_at


def load_manifests(source: Path) -> dict[tuple[str, str | None], ManifestEntry]:
    source = source.expanduser().resolve()
    candidates: list[Path]
    if source.is_file():
        candidates = [source]
    elif source.is_dir():
        direct = source / "manifest.json"
        if direct.is_file():
            candidates = [direct]
        else:
            candidates = sorted(source.glob("students/S[0-9][0-9][0-9]/manifest.json"))
    else:
        raise RetryBatchError("manifest 或整班批次目录不存在。")
    if not candidates:
        raise RetryBatchError("没有找到可用的练习 manifest。")

    entries: dict[tuple[str, str | None], ManifestEntry] = {}
    for candidate in candidates:
        try:
            manifest = practice_sheet._load_manifest(candidate)
        except practice_sheet.ManifestError as exc:
            raise RetryBatchError(str(exc)) from exc
        entry = ManifestEntry(manifest, candidate)
        if entry.key in entries:
            raise RetryBatchError("批次目录包含重复的练习实例。")
        entries[entry.key] = entry
    return entries


def _mastery(result: str, explicit: object, judgment: str) -> str | None:
    if explicit is not None:
        value = _text(explicit, "teacherMastery", 20)
        if value not in MASTERY_OPTIONS:
            raise RetryBatchError("teacherMastery 取值无效。")
        if value == "已掌握" and not judgment:
            raise RetryBatchError("标记已掌握时必须提供教师判断。")
        return value
    if result in {"partial", "incorrect"}:
        return "需再练"
    if result == "correct":
        return "练习中"
    return None


def build_plan(manifest_source: Path, raw: object) -> dict[str, Any]:
    manifests = load_manifests(manifest_source)
    if not isinstance(raw, Mapping) or set(raw) != {"observedAt", "pages"}:
        raise RetryBatchError("回收观察必须只包含 observedAt 和 pages。")
    observed_at = _parse_time(raw["observedAt"])
    pages = raw["pages"]
    if not isinstance(pages, list) or not pages:
        raise RetryBatchError("pages 必须是非空数组。")

    events: list[RetryEvent] = []
    seen_items: set[tuple[str, str | None, str]] = set()
    for page in pages:
        if not isinstance(page, Mapping) or set(page) != {"pageCode", "items"}:
            raise RetryBatchError("每个回收页面必须只包含 pageCode 和 items。")
        page_code = _text(page["pageCode"], "pageCode", 80)
        match = PAGE_CODE.fullmatch(page_code)
        if match is None:
            raise RetryBatchError("pageCode 格式无效。")
        instance = match.group("instance")
        instance_code = instance[1:] if instance else None
        key = (match.group("batch"), instance_code)
        entry = manifests.get(key)
        if entry is None:
            raise RetryBatchError("pageCode 无法定位到本次 manifest。")
        page_number = int(match.group("page"))
        items = page["items"]
        if not isinstance(items, list) or not items:
            raise RetryBatchError("每页 items 必须是非空数组。")

        for raw_item in items:
            if not isinstance(raw_item, Mapping):
                raise RetryBatchError("回收题目观察必须是对象。")
            allowed = {
                "itemNumber",
                "observedResponse",
                "markEvidence",
                "result",
                "teacherJudgment",
                "teacherMastery",
            }
            if set(raw_item) - allowed or not {
                "itemNumber",
                "observedResponse",
                "markEvidence",
                "result",
            }.issubset(raw_item):
                raise RetryBatchError("回收题目观察字段不完整或包含未知字段。")
            item_number = raw_item["itemNumber"]
            if isinstance(item_number, bool) or not isinstance(item_number, int):
                raise RetryBatchError("itemNumber 必须是整数。")
            if not 1 <= item_number <= len(entry.manifest.items):
                raise RetryBatchError("itemNumber 超出 manifest 题目范围。")
            item = entry.manifest.items[item_number - 1]
            item_key = (*key, item.item_code)
            if item_key in seen_items:
                raise RetryBatchError("同一道练习题在本批观察中重复出现。")
            seen_items.add(item_key)

            result = _text(raw_item["result"], "result", 30)
            if result not in RESULTS:
                raise RetryBatchError("result 取值无效。")
            observed_response = _text(
                raw_item["observedResponse"],
                "observedResponse",
                10_000,
                required=result not in {"uncertain", "not_observed"},
            )
            mark_evidence = _text(raw_item["markEvidence"], "markEvidence", 2_000)
            judgment = _text(
                raw_item.get("teacherJudgment", ""),
                "teacherJudgment",
                5_000,
                required=False,
            )
            student = entry.manifest.student
            events.append(
                RetryEvent(
                    batch_code=entry.manifest.batch_code,
                    instance_code=instance_code,
                    page_number=page_number,
                    item_code=item.item_code,
                    question_id=item.source.question_id,
                    variant_id=item.source.variant_id,
                    student_name=student.name if student is not None else None,
                    student_number=student.student_number if student is not None else None,
                    observed_response=observed_response,
                    mark_evidence=mark_evidence,
                    result=result,
                    teacher_judgment=judgment,
                    mastery=_mastery(result, raw_item.get("teacherMastery"), judgment),
                    observed_at=observed_at,
                )
            )

    events.sort(key=lambda event: (event.instance_code or "", event.item_code))
    projections = [event.base_projection() for event in events]
    return {
        "schemaVersion": PLAN_VERSION,
        "status": "prepared",
        "eventCount": len(events),
        "needsHumanCount": sum(1 for item in projections if item["needsHuman"]),
        "events": [event.private() for event in events],
        "baseProjections": projections,
    }


def validate_plan(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schemaVersion") != PLAN_VERSION:
        raise RetryBatchError("再练计划版本无效。")
    if raw.get("status") != "prepared":
        raise RetryBatchError("再练计划状态无效。")
    events = raw.get("events")
    projections = raw.get("baseProjections")
    if not isinstance(events, list) or not events or not isinstance(projections, list):
        raise RetryBatchError("再练计划内容无效。")
    if raw.get("eventCount") != len(events) or len(events) != len(projections):
        raise RetryBatchError("再练计划计数不一致。")
    ids: set[str] = set()
    expected_projections: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            raise RetryBatchError("再练事件结构无效。")
        event_id = event.get("eventId")
        payload = {key: value for key, value in event.items() if key != "eventId"}
        try:
            normalized = RetryEvent(**payload)
        except TypeError as exc:
            raise RetryBatchError("再练事件字段无效。") from exc
        if event_id != normalized.event_id or event_id in ids:
            raise RetryBatchError("再练事件稳定 ID 无效或重复。")
        ids.add(event_id)
        expected_projections.append(normalized.base_projection())
    if projections != expected_projections:
        raise RetryBatchError("再练计划 Base 投影与不可变事件不一致。")
    expected_needs_human = sum(1 for projection in expected_projections if projection["needsHuman"])
    needs_human_count = raw.get("needsHumanCount")
    if (
        isinstance(needs_human_count, bool)
        or not isinstance(needs_human_count, int)
        or needs_human_count != expected_needs_human
    ):
        raise RetryBatchError("再练计划人工处理计数与事件不一致。")
    return raw


def _write_new_json(path: Path, value: object) -> None:
    destination = path.expanduser().resolve()
    if destination.exists():
        raise RetryBatchError("输出计划已存在，请使用新文件名。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def append_events(plan: Mapping[str, Any], event_store: Path) -> tuple[int, int]:
    destination = event_store.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if destination.exists():
        try:
            for line in destination.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict) or not isinstance(value.get("eventId"), str):
                    raise ValueError("invalid event")
                existing.add(value["eventId"])
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise RetryBatchError("本地再练事件文件损坏，已停止写入。") from exc

    appended = 0
    duplicates = 0
    try:
        with destination.open("a", encoding="utf-8", newline="\n") as stream:
            for event in plan["events"]:
                event_id = str(event["eventId"])
                if event_id in existing:
                    duplicates += 1
                    continue
                envelope = {"schemaVersion": EVENT_VERSION, **event}
                stream.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n")
                existing.add(event_id)
                appended += 1
    except OSError as exc:
        raise RetryBatchError("无法追加本地再练事件。") from exc
    return appended, duplicates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--manifest", required=True, type=Path)
    prepare.add_argument("--input", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--plan", required=True, type=Path)

    commit = subparsers.add_parser("commit")
    commit.add_argument("--plan", required=True, type=Path)
    commit.add_argument("--event-store", required=True, type=Path)
    return parser


def _force_utf8_stdio() -> None:
    """Windows 控制台/管道默认 GBK；AI 消费的中文 JSON 必须始终按 UTF-8 输出。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            plan = build_plan(args.manifest, _read_json(args.input, "回收观察"))
            _write_new_json(args.output, plan)
            result = {
                "prepared": True,
                "eventCount": plan["eventCount"],
                "needsHumanCount": plan["needsHumanCount"],
            }
        else:
            plan = validate_plan(_read_json(args.plan, "再练计划"))
            if args.command == "validate":
                result = {
                    "valid": True,
                    "eventCount": plan["eventCount"],
                    "needsHumanCount": plan["needsHumanCount"],
                }
            else:
                appended, duplicates = append_events(plan, args.event_store)
                result = {
                    "committed": True,
                    "eventsAppended": appended,
                    "duplicateEvents": duplicates,
                    "baseProjectionPending": True,
                }
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except RetryBatchError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": "retry_batch_invalid", "message": str(exc)}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
