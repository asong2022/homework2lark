from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


homework2lark = sys.modules.get("homework2lark") or _load_module(
    "homework2lark", SCRIPTS / "homework2lark.py"
)
variant_catalog = _load_module("variant_catalog", SCRIPTS / "variant_catalog.py")


def _schema(field_types: dict[str, str]):
    fields = {}
    for index, (name, field_type) in enumerate(field_types.items(), start=1):
        options = (
            homework2lark.CORE_LITERACY_OPTIONS
            if name == variant_catalog.CORE_LITERACY_FIELD and field_type == "select"
            else frozenset()
        )
        source_table = (
            variant_catalog.QUESTION_TABLE
            if name == variant_catalog.CORE_LITERACY_FIELD and field_type == "lookup"
            else None
        )
        selected_field = (
            "fld_question_core"
            if name == variant_catalog.CORE_LITERACY_FIELD and field_type == "lookup"
            else None
        )
        field_id = (
            "fld_question_core"
            if name == variant_catalog.CORE_LITERACY_FIELD and field_type == "select"
            else f"fld_{index}"
        )
        fields[name] = homework2lark.BaseField(
            field_id,
            name,
            field_type,
            options,
            source_table,
            selected_field,
        )
    return homework2lark.BaseSchema(fields, {}, {})


class MemoryTable:
    def __init__(self, schema, records=None) -> None:
        self._schema = schema
        self.records = records or {}
        self.uploads: list[tuple[str, str, str]] = []
        self.downloads: list[tuple[str, str]] = []

    @property
    def resolved_table_name(self):
        return variant_catalog.QUESTION_TABLE

    def schema(self):
        return self._schema

    def list_records(
        self,
        fields: Sequence[str],
        *,
        view_id: str | None = None,
        filter_json=None,
        limit: int = 200,
    ):
        del view_id, limit
        records = list(self.records.values())
        if filter_json:
            for field_name, operator, expected in filter_json["conditions"]:
                if operator != "==":
                    raise AssertionError(f"unsupported operator: {operator}")
                records = [
                    record for record in records if record.fields.get(field_name) == expected
                ]
        return [
            homework2lark.BaseRecord(
                record.record_id,
                {field: copy.deepcopy(record.fields.get(field)) for field in fields},
            )
            for record in records
        ]

    def get_record(self, record_id: str, fields: Sequence[str]):
        record = self.records[record_id]
        return homework2lark.BaseRecord(
            record_id,
            {field: copy.deepcopy(record.fields.get(field)) for field in fields},
        )

    def patch_record(self, record_id: str, patch) -> None:
        self.records[record_id].fields.update(copy.deepcopy(patch))

    def upload_attachment(self, record_id: str, field_name: str, file_path: str):
        self.uploads.append((record_id, field_name, file_path))
        self.records[record_id].fields[field_name] = [{"file_token": "uploaded"}]

    def download_attachments(self, record_id: str, output_dir: str):
        self.downloads.append((record_id, output_dir))


class MemoryCatalogGateway:
    def __init__(self) -> None:
        question_types = {
            "系统题目ID": "text",
            "题目名称": "text",
            "图片题目": "attachment",
            "题干图片": "attachment",
            "题干文本": "text",
            "标准答案": "text",
            "核心素养": "select",
            "对应知识点": "text",
            "设计意图": "text",
            "页码": "lookup",
            "错题来源": "lookup",
            "本地修订版本": "number",
            "已审核时间": "datetime",
            "需人工处理": "checkbox",
            variant_catalog.REVERSE_LINK_FIELD: "link",
        }
        values = {name: None for name in question_types}
        values.update(
            {
                "系统题目ID": "problem_alpha",
                "题目名称": "两位数乘法错因分析",
                "图片题目": [{"file_token": "question"}],
                "题干文本": "计算34×21，并分析错误原因。",
                "核心素养": ["运算能力", "推理意识"],
                "设计意图": "理解部分积与数位意义。",
                "本地修订版本": 1,
                "已审核时间": "2026-07-15 09:00:00",
                "需人工处理": False,
                variant_catalog.REVERSE_LINK_FIELD: [],
            }
        )
        self.questions = MemoryTable(
            _schema(question_types),
            {"q_1": homework2lark.BaseRecord("q_1", values)},
        )
        self.variants = MemoryTable(_schema(dict(variant_catalog.EXPECTED_TYPES)))

    def ensure_table(self) -> bool:
        return False

    def validate_schema(self) -> None:
        return None

    def batch_create(self, rows: Sequence[Sequence[homework2lark.JSONValue]]):
        fields = (
            variant_catalog.PRIMARY_FIELD,
            variant_catalog.SOURCE_LINK_FIELD,
            variant_catalog.VARIANT_NUMBER_FIELD,
            variant_catalog.QUESTION_FIELD,
            variant_catalog.ANSWER_FIELD,
            variant_catalog.DESIGN_INTENT_FIELD,
            variant_catalog.GENERATED_AT_FIELD,
            variant_catalog.SYSTEM_ID_FIELD,
        )
        for row in rows:
            record_id = f"v_{len(self.variants.records) + 1}"
            values = {name: None for name in variant_catalog.VARIANT_FIELDS}
            values.update(dict(zip(fields, copy.deepcopy(list(row)), strict=True)))
            values[variant_catalog.IMAGE_FIELD] = []
            values[variant_catalog.CORE_LITERACY_FIELD] = ["运算能力", "推理意识"]
            values[variant_catalog.COLLECTION_ORDER_FIELD] = record_id.upper()
            self.variants.records[record_id] = homework2lark.BaseRecord(record_id, values)

    def list_entries(self):
        entries = []
        for record in self.variants.records.values():
            source = record.fields[variant_catalog.SOURCE_LINK_FIELD]
            entries.append(
                variant_catalog.CatalogEntry(
                    record_id=record.record_id,
                    stable_id=record.fields[variant_catalog.SYSTEM_ID_FIELD],
                    name=record.fields[variant_catalog.PRIMARY_FIELD],
                    source_record_id=source[0]["id"],
                    number=int(record.fields[variant_catalog.VARIANT_NUMBER_FIELD]),
                    question=record.fields[variant_catalog.QUESTION_FIELD],
                    answer_analysis=record.fields[variant_catalog.ANSWER_FIELD],
                    design_intent=record.fields[variant_catalog.DESIGN_INTENT_FIELD],
                    diagram_attachment_count=len(record.fields[variant_catalog.IMAGE_FIELD] or []),
                )
            )
        return entries


class VariantCatalogTests(unittest.TestCase):
    def test_stable_id_normalizes_whitespace_and_scopes_to_source(self) -> None:
        compact = variant_catalog.stable_variant_id("problem_a", "计算  26×14。")
        spaced = variant_catalog.stable_variant_id("problem_a", "计算\n26×14。")
        other = variant_catalog.stable_variant_id("problem_b", "计算26×14。")
        self.assertEqual(compact, spaced)
        self.assertNotEqual(compact, other)

    def test_schema_contains_design_intent_and_core_lookup_only(self) -> None:
        definitions = variant_catalog._field_definitions()
        names = {definition["name"] for definition in definitions}
        self.assertEqual(names, set(variant_catalog.VARIANT_FIELDS))
        self.assertIn(variant_catalog.DESIGN_INTENT_FIELD, names)
        lookup = next(
            item for item in definitions if item["name"] == variant_catalog.CORE_LITERACY_FIELD
        )
        self.assertEqual(lookup["type"], "lookup")
        self.assertNotIn("需人工处理", names)
        self.assertNotIn("题图说明", names)
        self.assertNotIn("生成Agent", names)
        self.assertNotIn("生成备注", names)

    def test_legacy_migration_command_is_closed_after_schema_cleanup(self) -> None:
        service = variant_catalog.VariantCatalogService(MemoryCatalogGateway())
        with self.assertRaises(homework2lark.SkillError) as captured:
            service.migrate_inline()
        self.assertEqual(captured.exception.code, "legacy_schema_removed")

    def test_write_appends_rows_and_reuses_identical_variants(self) -> None:
        gateway = MemoryCatalogGateway()
        service = variant_catalog.VariantCatalogService(gateway)
        payload = homework2lark.validate_generated_payload(
            {
                "questionId": "problem_alpha",
                "variants": [
                    {
                        "question": "计算35×24。",
                        "answerAnalysis": "840。",
                        "designIntent": "改变数值，巩固部分积对齐。",
                    },
                    {
                        "question": "找出143×26竖式中的错误并改正。",
                        "designIntent": "从错误诊断角度理解数位意义。",
                    },
                ],
            }
        )

        first = service.write(payload)
        second = service.write(payload)

        self.assertEqual(first["created"], 2)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["reused"], 2)
        self.assertEqual(len(gateway.variants.records), 2)
        self.assertEqual(
            {
                record.fields[variant_catalog.DESIGN_INTENT_FIELD]
                for record in gateway.variants.records.values()
            },
            {"改变数值，巩固部分积对齐。", "从错误诊断角度理解数位意义。"},
        )
        self.assertFalse(
            any("需要生成变式题" in record.fields for record in gateway.variants.records.values())
        )

    def test_payload_rejects_duplicate_questions_after_whitespace_normalization(self) -> None:
        with self.assertRaises(homework2lark.SkillError) as captured:
            homework2lark.validate_generated_payload(
                {
                    "questionId": "problem_alpha",
                    "variants": [
                        {
                            "question": "计算 35×24。",
                            "designIntent": "改变数值，巩固部分积对齐。",
                        },
                        {
                            "question": "计算\n35×24。",
                            "designIntent": "从另一角度理解部分积。",
                        },
                    ],
                }
            )

        self.assertEqual(captured.exception.code, "duplicate_variant")

    def test_write_boundary_rejects_manually_constructed_duplicate_payload(self) -> None:
        gateway = MemoryCatalogGateway()
        service = variant_catalog.VariantCatalogService(gateway)
        payload = homework2lark.GeneratedPayload(
            "problem_alpha",
            (
                homework2lark.Variant("计算 35×24。", None, "设计一"),
                homework2lark.Variant("计算\n35×24。", None, "设计二"),
            ),
        )

        with self.assertRaises(homework2lark.SkillError) as captured:
            service.write(payload)

        self.assertEqual(captured.exception.code, "duplicate_variant")
        self.assertEqual(gateway.variants.records, {})

    def test_write_uploads_optional_diagram_without_extra_description_column(self) -> None:
        gateway = MemoryCatalogGateway()
        service = variant_catalog.VariantCatalogService(gateway)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            png = Path(tmp) / "figure.png"
            html = Path(tmp) / "figure.html"
            png.write_bytes(b"png")
            html.write_text("<html></html>", encoding="utf-8")
            payload = homework2lark.validate_generated_payload(
                {
                    "questionId": "problem_alpha",
                    "variants": [
                        {
                            "question": "观察图形回答问题。",
                            "designIntent": "改变表征，促进图形关系理解。",
                            "diagram": {
                                "required": True,
                                "description": "一个标注边长的长方形。",
                                "localPng": str(png),
                                "editableHtml": str(html),
                            },
                        }
                    ],
                }
            )
            result = service.write(payload)

        self.assertEqual(result["diagramUploaded"], 1)
        self.assertEqual(len(gateway.variants.uploads), 1)
        available = service.list_available()
        self.assertEqual(available[0]["diagramAttachmentCount"], 1)
        self.assertEqual(available[0]["designIntent"], "改变表征，促进图形关系理解。")


if __name__ == "__main__":
    unittest.main()
