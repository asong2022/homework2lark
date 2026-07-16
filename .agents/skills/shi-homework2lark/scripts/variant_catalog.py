from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import homework2lark as core  # noqa: E402

VARIANT_TABLE = "变式题"
QUESTION_TABLE = "错题题目"

PRIMARY_FIELD = "变式题名称"
COLLECTION_ORDER_FIELD = "收录序号"
SOURCE_LINK_FIELD = "来源错题"
VARIANT_NUMBER_FIELD = "变式序号"
QUESTION_FIELD = "题干文本"
IMAGE_FIELD = "题干图片"
ANSWER_FIELD = "答案解析"
GENERATED_AT_FIELD = "生成时间"
DESIGN_INTENT_FIELD = "设计意图"
CORE_LITERACY_FIELD = "核心素养"
SYSTEM_ID_FIELD = "系统变式ID"
REVERSE_LINK_FIELD = "关联变式题"

VARIANT_FIELDS: tuple[str, ...] = (
    PRIMARY_FIELD,
    COLLECTION_ORDER_FIELD,
    SOURCE_LINK_FIELD,
    VARIANT_NUMBER_FIELD,
    QUESTION_FIELD,
    IMAGE_FIELD,
    ANSWER_FIELD,
    DESIGN_INTENT_FIELD,
    CORE_LITERACY_FIELD,
    GENERATED_AT_FIELD,
    SYSTEM_ID_FIELD,
)

EXPECTED_TYPES: dict[str, str] = {
    PRIMARY_FIELD: "text",
    COLLECTION_ORDER_FIELD: "auto_number",
    SOURCE_LINK_FIELD: "link",
    VARIANT_NUMBER_FIELD: "number",
    QUESTION_FIELD: "text",
    IMAGE_FIELD: "attachment",
    ANSWER_FIELD: "text",
    DESIGN_INTENT_FIELD: "text",
    CORE_LITERACY_FIELD: "lookup",
    GENERATED_AT_FIELD: "datetime",
    SYSTEM_ID_FIELD: "text",
}


@dataclass(frozen=True)
class CatalogEntry:
    record_id: str
    stable_id: str
    name: str
    source_record_id: str
    number: int
    question: str
    answer_analysis: str | None
    design_intent: str
    diagram_attachment_count: int


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalized_question(question: str) -> str:
    return " ".join(question.split())


def stable_variant_id(question_id: str, question: str) -> str:
    digest = hashlib.sha256(f"{question_id}\n{_normalized_question(question)}".encode()).hexdigest()
    return f"variant:v1:{digest[:32]}"


def _link_ids(value: core.JSONValue) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result.append(item["id"])
    return tuple(result)


def _number(value: core.JSONValue, field_name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value < 1
        or value % 1 != 0
    ):
        raise core.SkillError("variant_invalid", f"{field_name} 必须是正整数。")
    return int(value)


def _field_definitions() -> list[dict[str, object]]:
    return [
        {
            "name": PRIMARY_FIELD,
            "type": "text",
            "description": "教师可读名称：来源题目名称｜变式题N",
        },
        {
            "name": COLLECTION_ORDER_FIELD,
            "type": "auto_number",
            "style": {
                "rules": [
                    {"type": "text", "text": "V-"},
                    {"type": "incremental_number", "length": 3},
                ]
            },
        },
        {
            "name": SOURCE_LINK_FIELD,
            "type": "link",
            "link_table": QUESTION_TABLE,
            "bidirectional": True,
            "bidirectional_link_field_name": REVERSE_LINK_FIELD,
        },
        {
            "name": VARIANT_NUMBER_FIELD,
            "type": "number",
            "style": {
                "type": "plain",
                "precision": 0,
                "percentage": False,
                "thousands_separator": False,
            },
        },
        {"name": QUESTION_FIELD, "type": "text"},
        {"name": IMAGE_FIELD, "type": "attachment"},
        {"name": ANSWER_FIELD, "type": "text"},
        {"name": DESIGN_INTENT_FIELD, "type": "text"},
        {
            "name": CORE_LITERACY_FIELD,
            "type": "lookup",
            "from": QUESTION_TABLE,
            "select": CORE_LITERACY_FIELD,
            "aggregate": "unique",
            "where": {
                "logic": "and",
                "conditions": [
                    [
                        "题目名称",
                        "intersects",
                        {"type": "field_ref", "field": SOURCE_LINK_FIELD},
                    ]
                ],
            },
        },
        {
            "name": GENERATED_AT_FIELD,
            "type": "datetime",
            "style": {"format": "yyyy-MM-dd HH:mm"},
        },
        {
            "name": SYSTEM_ID_FIELD,
            "type": "text",
            "description": "AI 幂等同步键；教师常用视图隐藏",
        },
    ]


class VariantCatalogGateway:
    def __init__(
        self,
        runner: core.CommandRunner,
        *,
        base_title: str = core.DEFAULT_BASE_TITLE,
    ) -> None:
        self.runner = runner
        self.base_title = base_title
        self.questions = core.LarkCliGateway(
            runner, base_title=base_title, table_name=QUESTION_TABLE
        )
        self.variants = core.LarkCliGateway(runner, base_title=base_title, table_name=VARIANT_TABLE)

    def _candidate(self) -> core.ResolvedBaseCandidate:
        matches: dict[str, core.ResolvedBaseCandidate] = {}
        for candidate in core.resolve_base_candidates(self.runner, self.base_title):
            names = {core._text(table.get("name")) for table in candidate.tables}
            if QUESTION_TABLE in names:
                matches[candidate.base_token] = candidate
        if len(matches) != 1:
            raise core.SkillError("schema_mismatch", "无法唯一定位小学数学错题学习 Base。")
        return next(iter(matches.values()))

    def ensure_table(self) -> bool:
        candidate = self._candidate()
        tables = [
            table for table in candidate.tables if core._text(table.get("name")) == VARIANT_TABLE
        ]
        if len(tables) > 1:
            raise core.SkillError("schema_mismatch", "存在多个同名变式题表。")
        created = False
        if not tables:
            self.runner.run(
                [
                    "base",
                    "+table-create",
                    "--base-token",
                    candidate.base_token,
                    "--name",
                    VARIANT_TABLE,
                    "--fields",
                    _json(_field_definitions()),
                    "--as",
                    "user",
                    "--format",
                    "json",
                ]
            )
            created = True
            self.variants = core.LarkCliGateway(
                self.runner, base_title=self.base_title, table_name=VARIANT_TABLE
            )
        self.validate_schema()
        return created

    def validate_schema(self) -> None:
        schema = self.variants.schema()
        errors: list[str] = []
        for field_name, expected_type in EXPECTED_TYPES.items():
            actual = schema.fields.get(field_name)
            if actual is None:
                errors.append(f"缺少 {field_name}")
            elif actual.field_type != expected_type:
                errors.append(f"{field_name} 应为 {expected_type}，实际为 {actual.field_type}")
        reverse = self.questions.schema().fields.get(REVERSE_LINK_FIELD)
        if reverse is None or reverse.field_type != "link":
            errors.append(f"错题题目缺少反向关联 {REVERSE_LINK_FIELD}")
        core_lookup = schema.fields.get(CORE_LITERACY_FIELD)
        question_core = self.questions.schema().fields.get(CORE_LITERACY_FIELD)
        if question_core is None or question_core.field_type != "select":
            errors.append("错题题目缺少核心素养多选事实源")
        elif (
            core_lookup is None
            or core_lookup.source_table not in {QUESTION_TABLE, self.questions.resolved_table_name}
            or core_lookup.selected_field not in {CORE_LITERACY_FIELD, question_core.field_id}
        ):
            errors.append("变式题.核心素养必须查找引用错题题目.核心素养")
        if errors:
            raise core.SkillError("schema_mismatch", "；".join(errors))

    def batch_create(self, rows: Sequence[Sequence[core.JSONValue]]) -> None:
        if not rows:
            return
        base_token, table_id = self.variants._context()
        payload: dict[str, object] = {
            "fields": [
                PRIMARY_FIELD,
                SOURCE_LINK_FIELD,
                VARIANT_NUMBER_FIELD,
                QUESTION_FIELD,
                ANSWER_FIELD,
                DESIGN_INTENT_FIELD,
                GENERATED_AT_FIELD,
                SYSTEM_ID_FIELD,
            ],
            "rows": [list(row) for row in rows],
        }
        self.runner.run(
            [
                "base",
                "+record-batch-create",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--as",
                "user",
                "--json",
                _json(payload),
                "--format",
                "json",
            ]
        )

    def list_entries(self) -> list[CatalogEntry]:
        records = self.variants.list_records(VARIANT_FIELDS, limit=200)
        entries: list[CatalogEntry] = []
        for record in records:
            stable_id = core._text(record.fields.get(SYSTEM_ID_FIELD))
            question = core._text(record.fields.get(QUESTION_FIELD))
            source_ids = _link_ids(record.fields.get(SOURCE_LINK_FIELD))
            if not stable_id or not question or len(source_ids) != 1:
                raise core.SkillError("variant_invalid", "变式题缺少稳定键、题干或唯一来源错题。")
            entries.append(
                CatalogEntry(
                    record_id=record.record_id,
                    stable_id=stable_id,
                    name=core._text(record.fields.get(PRIMARY_FIELD)),
                    source_record_id=source_ids[0],
                    number=_number(
                        record.fields.get(VARIANT_NUMBER_FIELD),
                        VARIANT_NUMBER_FIELD,
                    ),
                    question=question,
                    answer_analysis=(core._text(record.fields.get(ANSWER_FIELD)) or None),
                    design_intent=core._text(record.fields.get(DESIGN_INTENT_FIELD)),
                    diagram_attachment_count=core._attachment_count(record.fields.get(IMAGE_FIELD)),
                )
            )
        return entries


class VariantCatalogService:
    def __init__(self, gateway: VariantCatalogGateway) -> None:
        self.gateway = gateway

    def migrate_inline(self) -> dict[str, core.JSONValue]:
        raise core.SkillError(
            "legacy_schema_removed",
            "旧同行变式字段已完成迁移并删除，不能再次执行 migrate-inline。",
        )

    def write(self, payload: core.GeneratedPayload) -> dict[str, core.JSONValue]:
        requested_stable_ids = [
            stable_variant_id(payload.question_id, variant.question) for variant in payload.variants
        ]
        if len(set(requested_stable_ids)) != len(requested_stable_ids):
            raise core.SkillError("duplicate_variant", "同一次写入不能包含重复的变式题题干。")
        self.gateway.ensure_table()
        question_schema = self.gateway.questions.schema()
        stable_question_field = core.question_id_field(question_schema)
        source_matches = self.gateway.questions.list_records(
            core.read_fields(question_schema),
            filter_json={
                "logic": "and",
                "conditions": [[stable_question_field, "==", payload.question_id]],
            },
            limit=2,
        )
        if len(source_matches) != 1:
            raise core.SkillError("record_not_found", "没有唯一匹配的已审核原题。")
        source = source_matches[0]
        core.ensure_source_eligible(source)

        existing_entries = self.gateway.list_entries()
        by_stable = {entry.stable_id: entry for entry in existing_entries}
        if len(by_stable) != len(existing_entries):
            raise core.SkillError(
                "duplicate_system_variant_id", "变式题表存在重复稳定键，已停止写入。"
            )
        source_entries = [
            entry for entry in existing_entries if entry.source_record_id == source.record_id
        ]
        next_number = max((entry.number for entry in source_entries), default=0) + 1
        source_name = core._text(source.fields.get("题目名称")) or "已审核错题"
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        rows: list[list[core.JSONValue]] = []
        planned: list[tuple[str, core.Variant]] = []
        reused = 0

        for variant in payload.variants:
            stable_id = stable_variant_id(payload.question_id, variant.question)
            current = by_stable.get(stable_id)
            if current is not None:
                self._assert_same(
                    current,
                    variant.question,
                    variant.answer_analysis,
                    variant.design_intent,
                    source.record_id,
                    allow_empty_design_intent=True,
                )
                if not current.design_intent:
                    self.gateway.variants.patch_record(
                        current.record_id,
                        {DESIGN_INTENT_FIELD: variant.design_intent},
                    )
                reused += 1
                planned.append((stable_id, variant))
                continue
            number = next_number + len(rows)
            rows.append(
                [
                    f"{source_name}｜变式题{number}",
                    [{"id": source.record_id}],
                    number,
                    variant.question,
                    variant.answer_analysis,
                    variant.design_intent,
                    timestamp,
                    stable_id,
                ]
            )
            planned.append((stable_id, variant))

        self.gateway.batch_create(rows)
        written_entries = self.gateway.list_entries()
        by_stable = {entry.stable_id: entry for entry in written_entries}
        if len(by_stable) != len(written_entries):
            raise core.SkillError(
                "duplicate_system_variant_id", "变式题表存在重复稳定键，已停止后续操作。"
            )
        uploaded = 0
        for stable_id, variant in planned:
            entry = by_stable.get(stable_id)
            if entry is None:
                raise core.SkillError("write_incomplete", "变式题写入后无法回读。")
            self._assert_same(
                entry,
                variant.question,
                variant.answer_analysis,
                variant.design_intent,
                source.record_id,
            )
            if variant.diagram is None:
                continue
            if entry.diagram_attachment_count == 0:
                if variant.diagram.local_png is None:
                    raise core.SkillError("diagram_incomplete", "变式题缺少题图文件。")
                self.gateway.variants.upload_attachment(
                    entry.record_id, IMAGE_FIELD, variant.diagram.local_png
                )
                uploaded += 1
            refreshed = self.gateway.variants.get_record(entry.record_id, VARIANT_FIELDS)
            if core._attachment_count(refreshed.fields.get(IMAGE_FIELD)) != 1:
                raise core.SkillError("diagram_incomplete", "题图上传后回读不完整。")
        return {
            "questionId": payload.question_id,
            "created": len(rows),
            "reused": reused,
            "diagramUploaded": uploaded,
        }

    def list_available(self) -> list[dict[str, core.JSONValue]]:
        self.gateway.validate_schema()
        entries = self.gateway.list_entries()
        question_schema = self.gateway.questions.schema()
        question_fields = tuple(
            field
            for field in (*core.QUESTION_ID_FIELDS, "题目名称")
            if field in question_schema.fields
        )
        questions = self.gateway.questions.list_records(question_fields, limit=200)
        source_ids = {record.record_id: core.question_id(record) for record in questions}
        result: list[dict[str, core.JSONValue]] = []
        for entry in sorted(entries, key=lambda item: (item.source_record_id, item.number)):
            result.append(
                {
                    "variantId": entry.stable_id,
                    "sourceQuestionId": source_ids.get(entry.source_record_id, ""),
                    "variantNumber": entry.number,
                    "name": entry.name,
                    "question": entry.question,
                    "answerAnalysis": entry.answer_analysis,
                    "designIntent": entry.design_intent,
                    "diagramAttachmentCount": entry.diagram_attachment_count,
                }
            )
        return result

    def download_images(self, variant_id: str, output_dir: str) -> dict[str, core.JSONValue]:
        self.gateway.validate_schema()
        matches = [entry for entry in self.gateway.list_entries() if entry.stable_id == variant_id]
        if len(matches) != 1:
            raise core.SkillError("record_not_found", "没有唯一匹配的可下载变式题。")
        entry = matches[0]
        safe_output = core.validate_relative_directory(output_dir)
        if entry.diagram_attachment_count:
            self.gateway.variants.download_attachments(entry.record_id, safe_output)
        return {
            "variantId": entry.stable_id,
            "downloadedAttachmentCount": entry.diagram_attachment_count,
            "outputDir": safe_output,
        }

    @staticmethod
    def _assert_same(
        entry: CatalogEntry,
        question: str,
        answer: str | None,
        design_intent: str,
        source_record_id: str,
        *,
        allow_empty_design_intent: bool = False,
    ) -> None:
        intent_mismatch = entry.design_intent != design_intent and not (
            allow_empty_design_intent and not entry.design_intent
        )
        if (
            entry.question != question
            or entry.answer_analysis != answer
            or intent_mismatch
            or entry.source_record_id != source_record_id
        ):
            raise core.SkillError("variant_conflict", "相同稳定键的变式题内容或来源不一致。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Feishu Base variant catalog")
    parser.add_argument(
        "--base-title",
        default=core.DEFAULT_BASE_TITLE,
    )
    parser.add_argument("--lark-cli-command", default="lark-cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema-check")
    commands.add_parser("ensure-schema")
    commands.add_parser("migrate-inline")
    commands.add_parser("list-available")
    validate = commands.add_parser("validate")
    validate.add_argument("--input", required=True)
    write = commands.add_parser("write")
    write.add_argument("--input", required=True)
    download = commands.add_parser("download-images")
    download.add_argument("--variant-id", required=True)
    download.add_argument("--output-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runner = core.SubprocessRunner(args.lark_cli_command)
        gateway = VariantCatalogGateway(runner, base_title=args.base_title)
        service = VariantCatalogService(gateway)
        if args.command == "schema-check":
            gateway.validate_schema()
            data: core.JSONValue = {
                "table": VARIANT_TABLE,
                "fieldCount": len(EXPECTED_TYPES),
                "sourceTable": QUESTION_TABLE,
            }
        elif args.command == "ensure-schema":
            data = {"table": VARIANT_TABLE, "created": gateway.ensure_table()}
        elif args.command == "migrate-inline":
            data = service.migrate_inline()
        elif args.command == "list-available":
            data = service.list_available()
        elif args.command == "validate":
            payload = core.validate_generated_payload(core.load_json_input(args.input))
            data = {
                "questionId": payload.question_id,
                "variantCount": len(payload.variants),
                "diagramCount": sum(
                    1 for variant in payload.variants if variant.diagram is not None
                ),
            }
        elif args.command == "write":
            payload = core.validate_generated_payload(core.load_json_input(args.input))
            data = service.write(payload)
        elif args.command == "download-images":
            data = service.download_images(args.variant_id, args.output_dir)
        else:
            raise core.SkillError("invalid_command", "不支持的命令。")
        print(_json({"ok": True, "data": data}))
        return 0
    except core.SkillError as exc:
        print(_json({"ok": False, "error": exc.public()}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
