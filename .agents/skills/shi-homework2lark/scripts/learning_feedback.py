#!/usr/bin/env python3
"""Record anonymous retry feedback locally and project a summary to Lark Base."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import homework2lark as core  # noqa: E402

RESULTS = frozenset(("correct", "partial", "incorrect", "not_observed"))
MASTERY_OPTIONS = frozenset(("未开始", "练习中", "需再练", "已掌握"))
FEEDBACK_FIELD_TYPES = {
    "掌握状态": "select",
    "最近再练时间": "datetime",
}


@dataclass(frozen=True)
class FeedbackEvent:
    question_id: str
    variant_number: int | None
    observed_response: str
    teacher_judgment: str
    result: str
    mastery: str
    summary: str
    occurred_at: str

    @property
    def event_id(self) -> str:
        encoded = json.dumps(
            asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "feedback_" + hashlib.sha256(encoded).hexdigest()[:24]


class FeedbackService:
    def __init__(self, gateway: core.Gateway) -> None:
        self.gateway = gateway

    def preview(self, record_id: str, event: FeedbackEvent) -> dict[str, core.JSONValue]:
        schema, record = self._record(record_id)
        del schema
        self._validate_target(record, event)
        return {
            "eventId": event.event_id,
            "questionId": event.question_id,
            "variantNumber": event.variant_number,
            "result": event.result,
            "summary": event.summary,
            "mastery": event.mastery,
            "occurredAt": event.occurred_at,
            "baseFields": list(FEEDBACK_FIELD_TYPES),
            "willAppendLocalHistory": True,
            "willOverwriteTypicalStudentError": False,
        }

    def record(
        self, record_id: str, event: FeedbackEvent, event_store: str
    ) -> dict[str, core.JSONValue]:
        schema, before = self._record(record_id)
        self._validate_target(before, event)
        relative_store, resolved_store = validate_event_store(event_store)
        appended = append_event_once(resolved_store, event)
        event_time = parse_datetime(event.occurred_at)
        current_time = parse_base_datetime(before.fields.get("最近再练时间"))
        if current_time is not None and event_time <= current_time:
            return {
                "eventId": event.event_id,
                "questionId": event.question_id,
                "localHistory": relative_store,
                "historyAppended": appended,
                "baseProjectionUpdated": False,
                "mastery": core._select(before.fields.get("掌握状态")),
                "projectionSkippedReason": "not_newer_than_current",
            }

        patch: dict[str, core.JSONValue] = {
            "掌握状态": event.mastery,
            "最近再练时间": format_base_datetime(event.occurred_at),
        }
        snapshot = {
            name: before.fields.get(name)
            for name in schema.fields
            if name not in FEEDBACK_FIELD_TYPES
        }
        self.gateway.patch_record(record_id, patch)
        after = self.gateway.get_record(record_id, tuple(schema.fields))
        for name, expected in snapshot.items():
            if not core._json_equal(after.fields.get(name), expected):
                raise core.SkillError(
                    "feedback_source_changed", "再练反馈写回改变了非反馈字段，请人工检查。"
                )
        if core._select(after.fields.get("掌握状态")) != event.mastery:
            raise core.SkillError("feedback_write_failed", "掌握状态回读失败。")
        if core._empty(after.fields.get("最近再练时间")):
            raise core.SkillError("feedback_write_failed", "最近再练时间回读失败。")
        return {
            "eventId": event.event_id,
            "questionId": event.question_id,
            "localHistory": relative_store,
            "historyAppended": appended,
            "baseProjectionUpdated": True,
            "mastery": event.mastery,
        }

    def _record(self, record_id: str) -> tuple[core.BaseSchema, core.BaseRecord]:
        schema = self.gateway.schema()
        core.validate_schema(schema)
        validate_feedback_schema(schema)
        record = self.gateway.get_record(record_id, tuple(schema.fields))
        core.ensure_source_eligible(record)
        return schema, record

    @staticmethod
    def _validate_target(record: core.BaseRecord, event: FeedbackEvent) -> None:
        if core.question_id(record) != event.question_id:
            raise core.SkillError("question_id_mismatch", "反馈的题目 ID 与目标 Base 记录不一致。")


def validate_feedback_schema(schema: core.BaseSchema) -> None:
    for name, expected_type in FEEDBACK_FIELD_TYPES.items():
        field = schema.fields.get(name)
        if field is None or field.field_type != expected_type:
            raise core.SkillError("schema_mismatch", f"Base 再练反馈字段无效：{name}。")
    if schema.fields["掌握状态"].options != MASTERY_OPTIONS:
        raise core.SkillError(
            "schema_mismatch", "掌握状态选项必须是未开始、练习中、需再练、已掌握。"
        )


def validate_feedback_payload(raw: core.JSONValue) -> FeedbackEvent:
    obj = core._as_object(raw, "再练反馈")
    allowed = {
        "questionId",
        "variantNumber",
        "observedResponse",
        "teacherJudgment",
        "result",
        "mastery",
        "summary",
        "occurredAt",
    }
    if set(obj) - allowed:
        raise core.SkillError("invalid_feedback", "再练反馈包含未支持或身份相关字段。")
    question_id = core._require_nonempty_text(obj.get("questionId"), "questionId", maximum=120)
    if not question_id.startswith("problem_"):
        raise core.SkillError("invalid_feedback", "questionId 必须是 problem_ 稳定 ID。")
    variant_number = obj.get("variantNumber")
    if variant_number is not None and (
        not isinstance(variant_number, int)
        or isinstance(variant_number, bool)
        or not 1 <= variant_number <= 5
    ):
        raise core.SkillError("invalid_feedback", "variantNumber 必须为空或 1～5。")
    result = core._require_nonempty_text(obj.get("result"), "result", maximum=30)
    if result not in RESULTS:
        raise core.SkillError("invalid_feedback", "result 取值无效。")
    observed = obj.get("observedResponse", "")
    teacher = obj.get("teacherJudgment", "")
    if not isinstance(observed, str) or len(observed) > 10_000:
        raise core.SkillError("invalid_feedback", "observedResponse 必须是不超过 10000 字的文本。")
    if not isinstance(teacher, str) or len(teacher) > 5_000:
        raise core.SkillError("invalid_feedback", "teacherJudgment 必须是不超过 5000 字的文本。")
    if result != "not_observed" and not observed.strip():
        raise core.SkillError("invalid_feedback", "有作答结论时必须填写真实 observedResponse。")
    mastery = core._require_nonempty_text(obj.get("mastery"), "mastery", maximum=20)
    if mastery not in MASTERY_OPTIONS:
        raise core.SkillError("invalid_feedback", "mastery 取值无效。")
    summary = core._require_nonempty_text(obj.get("summary"), "summary", maximum=2_000)
    occurred_at = core._require_nonempty_text(obj.get("occurredAt"), "occurredAt", maximum=50)
    parse_datetime(occurred_at)
    return FeedbackEvent(
        question_id,
        variant_number,
        observed.strip(),
        teacher.strip(),
        result,
        mastery,
        summary,
        occurred_at,
    )


def parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise core.SkillError("invalid_feedback", "occurredAt 必须是 ISO 8601 时间。") from exc
    if parsed.tzinfo is None:
        raise core.SkillError("invalid_feedback", "occurredAt 必须包含时区。")
    return parsed


def format_base_datetime(value: str) -> str:
    return parse_datetime(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def parse_base_datetime(value: core.JSONValue) -> datetime | None:
    if core._empty(value):
        return None
    if isinstance(value, list) and len(value) == 1:
        item = value[0]
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            value = item["text"]
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise core.SkillError(
                "feedback_current_time_invalid", "Base 最近再练时间格式无效，已停止覆盖。"
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OSError, OverflowError, ValueError) as exc:
            raise core.SkillError(
                "feedback_current_time_invalid", "Base 最近再练时间格式无效，已停止覆盖。"
            ) from exc
    raise core.SkillError(
        "feedback_current_time_invalid", "Base 最近再练时间格式无效，已停止覆盖。"
    )


def validate_event_store(path_value: str) -> tuple[str, Path]:
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".jsonl":
        raise core.SkillError("unsafe_path", "事件文件必须是当前目录内的相对 .jsonl 路径。")
    resolved = (Path.cwd() / path).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise core.SkillError("unsafe_path", "事件文件超出当前工作目录。")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(path).replace("\\", "/"), resolved


def append_event_once(path: Path, event: FeedbackEvent) -> bool:
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                decoded = json.loads(line)
                if not isinstance(decoded, dict) or not isinstance(decoded.get("eventId"), str):
                    raise ValueError("invalid event")
                if decoded["eventId"] == event.event_id:
                    return False
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise core.SkillError(
                "event_store_invalid", "本地再练事件文件损坏，已停止写入。"
            ) from exc
    envelope = {
        "schemaVersion": 1,
        "eventId": event.event_id,
        **asdict(event),
    }
    try:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        raise core.SkillError("event_store_unwritable", "无法追加本地再练事件。") from exc
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-title",
        default=os.environ.get("SHI_HOMEWORK2LARK_BASE_TITLE", core.DEFAULT_BASE_TITLE),
    )
    parser.add_argument("--table-name", default=core.DEFAULT_TABLE_NAME)
    parser.add_argument(
        "--lark-cli-command", default=os.environ.get("LARK_CLI_COMMAND", "lark-cli")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("schema-check")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", required=True)
    for name in ("preview", "record"):
        command = subparsers.add_parser(name)
        command.add_argument("--record-id", required=True)
        command.add_argument("--input", required=True)
        if name == "record":
            command.add_argument("--event-store", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "schema-check":
            gateway = core.LarkCliGateway(
                core.SubprocessRunner(args.lark_cli_command),
                base_title=args.base_title,
                table_name=args.table_name,
            )
            schema = gateway.schema()
            core.validate_schema(schema)
            validate_feedback_schema(schema)
            result: core.JSONValue = {
                "valid": True,
                "fields": list(FEEDBACK_FIELD_TYPES),
                "masteryOptions": sorted(MASTERY_OPTIONS),
            }
        else:
            event = validate_feedback_payload(core.load_json_input(args.input))
        if args.command == "validate":
            result: core.JSONValue = {
                "valid": True,
                "eventId": event.event_id,
                "questionId": event.question_id,
            }
        elif args.command in {"preview", "record"}:
            gateway = core.LarkCliGateway(
                core.SubprocessRunner(args.lark_cli_command),
                base_title=args.base_title,
                table_name=args.table_name,
            )
            service = FeedbackService(gateway)
            if args.command == "preview":
                result = service.preview(args.record_id, event)
            elif args.command == "record":
                result = service.record(args.record_id, event, args.event_store)
            else:
                raise core.SkillError("unsupported_command", "不支持的命令。")
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except core.SkillError as exc:
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
