from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "homework2lark.py"
SPEC = importlib.util.spec_from_file_location("homework2lark", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load homework2lark module")
homework2lark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = homework2lark
SPEC.loader.exec_module(homework2lark)


class MemoryGateway:
    def __init__(self) -> None:
        field_types = {
            "题目唯一ID": "text",
            "题目名称": "text",
            homework2lark.COLLECTION_ORDER_FIELD: "auto_number",
            "图片题目": "attachment",
            "题干图片": "attachment",
            "题干文本": "text",
            "标准答案": "text",
            "核心素养": "select",
            "对应知识点": "text",
            "设计意图": "text",
            "时间": "lookup",
            "年级": "lookup",
            "页码": "lookup",
            "错题来源": "lookup",
            "本地修订版本": "number",
            "已审核时间": "datetime",
            homework2lark.TYPICAL_ERROR_FIELD: "lookup",
            homework2lark.ERROR_PATTERN_FIELD: "lookup",
            homework2lark.ERROR_CAUSE_SUMMARY_FIELD: "text",
            **homework2lark.EXPECTED_FIELD_TYPES,
        }
        fields = {}
        for index, (name, field_type) in enumerate(field_types.items(), start=1):
            options = homework2lark.CORE_LITERACY_OPTIONS if name == "核心素养" else frozenset()
            fields[name] = homework2lark.BaseField(f"fld_{index}", name, field_type, options)
        views = {
            name: homework2lark.BaseView(f"view_{index}", name)
            for index, name in enumerate(homework2lark.EXPECTED_VIEW_FILTERS, start=1)
        }
        filters = {
            name: {
                "logic": "and",
                "conditions": [list(condition) for condition in conditions],
            }
            for name, conditions in homework2lark.EXPECTED_VIEW_FILTERS.items()
        }
        self._schema = homework2lark.BaseSchema(fields, views, filters)
        self.records = {
            "rec_1": self._record("rec_1", "problem_alpha", linked=False),
            "rec_2": self._record("rec_2", "problem_beta", linked=True),
        }

    def _record(self, record_id: str, question_id: str, *, linked: bool):
        values = {name: None for name in self._schema.fields}
        values.update(
            {
                "题目唯一ID": question_id,
                "题目名称": "乘法总价问题" if not linked else "折角问题",
                homework2lark.COLLECTION_ORDER_FIELD: "1" if not linked else "2",
                "图片题目": [{"file_token": "not-exposed"}],
                "题干图片": [],
                "题干文本": "一盒彩笔24元，买3盒一共多少元？",
                "标准答案": "72元",
                "核心素养": ["运算能力", "应用意识"],
                "对应知识点": "乘法应用；总价计算",
                "设计意图": "考查学生用乘法模型解决总价问题。",
                "时间": "2026/07/14",
                "年级": "三年级",
                "页码": "116",
                "错题来源": "教材",
                "本地修订版本": 1,
                "已审核时间": "2026-07-14 10:30:00",
                homework2lark.MANUAL_ATTENTION_FIELD: False,
                homework2lark.REVERSE_VARIANT_LINK_FIELD: ([{"id": "variant_1"}] if linked else []),
                homework2lark.TYPICAL_ERROR_FIELD: "漏写十位部分积。",
                homework2lark.ERROR_PATTERN_FIELD: "只计算个位部分积。",
                homework2lark.ERROR_CAUSE_SUMMARY_FIELD: "未理解数位对应关系：3人",
            }
        )
        return homework2lark.BaseRecord(record_id, values)

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
        del limit
        records = list(self.records.values())
        if view_id == self._schema.views[homework2lark.SELECTED_VIEW].view_id:
            records = [
                record
                for record in records
                if not record.fields[homework2lark.REVERSE_VARIANT_LINK_FIELD]
                and record.fields[homework2lark.MANUAL_ATTENTION_FIELD] is False
            ]
        if filter_json:
            records = [record for record in records if self._matches(record, filter_json)]
        return [
            homework2lark.BaseRecord(
                record.record_id,
                {name: copy.deepcopy(record.fields.get(name)) for name in fields},
            )
            for record in records
        ]

    def _matches(self, record, filter_json):
        for field_name, operator, *rest in filter_json["conditions"]:
            actual = record.fields.get(field_name)
            expected = rest[0] if rest else None
            if operator == "==" and actual != expected:
                return False
            if operator == "empty" and actual not in (None, "", []):
                return False
            if operator == "non_empty" and actual in (None, "", []):
                return False
        return True

    def get_record(self, record_id: str, fields: Sequence[str]):
        record = self.records[record_id]
        return homework2lark.BaseRecord(
            record_id,
            {name: copy.deepcopy(record.fields.get(name)) for name in fields},
        )

    def patch_record(self, record_id: str, patch):
        self.records[record_id].fields.update(copy.deepcopy(patch))

    def download_attachments(self, record_id: str, output_dir: str):
        del record_id, output_dir

    def upload_attachment(self, record_id: str, field_name: str, file_path: str):
        del record_id, field_name, file_path


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: Sequence[str], *, retry_read: bool = False):
        self.calls.append(list(args))
        command = args[1]
        if command == "+title-resolve":
            return {"ok": True, "data": {"base_token": "base_runtime"}}
        if command == "+table-list":
            return {
                "ok": True,
                "data": {"tables": [{"id": "tbl_runtime", "name": "questions"}]},
            }
        if command in {"+record-list", "+record-get"}:
            return {
                "ok": True,
                "data": {
                    "fields": ["题目唯一ID", "题干文本"],
                    "data": [["problem_alpha", "一道完整题"]],
                    "record_id_list": ["rec_runtime"],
                    "has_more": False,
                },
            }
        raise AssertionError(f"Unexpected command: {command}; retry={retry_read}")


class Homework2LarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = MemoryGateway()
        self.service = homework2lark.Homework2LarkService(self.gateway)

    def test_schema_and_pending_view_use_reverse_variant_link(self) -> None:
        schema = self.service.schema_check()
        selected = self.service.list_selected()

        self.assertEqual(schema["generatedFieldCount"], 2)
        self.assertEqual([item["questionId"] for item in selected], ["problem_alpha"])
        self.assertEqual(selected[0]["coreLiteracy"], ["运算能力", "应用意识"])
        self.assertEqual(selected[0]["designIntent"], "考查学生用乘法模型解决总价问题。")
        self.assertTrue(selected[0]["selected"])
        self.assertEqual(selected[0]["storedVariantCount"], 0)

    def test_payload_requires_design_intent_and_keeps_answer_optional(self) -> None:
        payload = homework2lark.validate_generated_payload(
            {
                "questionId": "problem_alpha",
                "variants": [
                    {
                        "question": "计算35×24。",
                        "designIntent": "改变数值，巩固两位数乘两位数。",
                    }
                ],
            }
        )
        self.assertIsNone(payload.variants[0].answer_analysis)
        self.assertEqual(payload.variants[0].design_intent, "改变数值，巩固两位数乘两位数。")

        with self.assertRaisesRegex(homework2lark.SkillError, "designIntent"):
            homework2lark.validate_generated_payload(
                {
                    "questionId": "problem_alpha",
                    "variants": [{"question": "缺少设计意图"}],
                }
            )

    def test_payload_rejects_removed_generation_metadata(self) -> None:
        with self.assertRaisesRegex(homework2lark.SkillError, "未支持"):
            homework2lark.validate_generated_payload(
                {
                    "questionId": "problem_alpha",
                    "variants": [{"question": "题目", "designIntent": "意图", "category": "拓展"}],
                    "agent": "codex",
                }
            )

    def test_legacy_same_row_commands_are_explicitly_disabled(self) -> None:
        payload = homework2lark.validate_generated_payload(
            {
                "questionId": "problem_alpha",
                "variants": [{"question": "题目", "designIntent": "意图"}],
            }
        )
        for operation in (
            lambda: self.service.write("rec_1", payload, replace_all=False),
            lambda: self.service.attach_diagram("rec_1", 1, "figure.png"),
            lambda: self.service.review("rec_1"),
            self.service.list_available,
        ):
            with self.assertRaises(homework2lark.SkillError) as captured:
                operation()
            self.assertEqual(captured.exception.code, "independent_variant_catalog_required")

    def test_source_eligibility_still_requires_local_review_evidence(self) -> None:
        record = self.gateway.records["rec_1"].fields
        record["本地修订版本"] = None
        with self.assertRaisesRegex(homework2lark.SkillError, "缺少本地审核版本"):
            self.service.list_selected()

    def test_json_input_accepts_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd().parent) as tmp:
            payload_path = Path(tmp) / "payload.json"
            payload_path.write_text('{"scope":"outside"}', encoding="utf-8")
            loaded = homework2lark.load_json_input(str(payload_path.resolve()))
        self.assertEqual(loaded, {"scope": "outside"})

    def test_lark_gateway_parses_columnar_records(self) -> None:
        runner = FakeRunner()
        gateway = homework2lark.LarkCliGateway(runner)
        records = gateway.list_records(("题目唯一ID", "题干文本"), limit=2)
        self.assertEqual(records[0].record_id, "rec_runtime")
        self.assertEqual(records[0].fields["题干文本"], "一道完整题")

    def test_direct_base_is_selected_from_duplicate_title_candidates(self) -> None:
        class DuplicateTitleRunner:
            def run(self, args: Sequence[str], *, retry_read: bool = False):
                del retry_read
                if args[1] == "+title-resolve":
                    return {
                        "ok": True,
                        "data": {
                            "candidates": [
                                {"base_token": "direct", "title": "小学数学错题学习库"},
                                {"base_token": "wrapper", "title": "小学数学错题学习库"},
                            ]
                        },
                    }
                token = args[args.index("--base-token") + 1]
                return {
                    "ok": True,
                    "data": {
                        "tables": (
                            [{"id": "tbl_questions", "name": "错题题目"}]
                            if token == "direct"
                            else []
                        )
                    },
                }

        gateway = homework2lark.LarkCliGateway(DuplicateTitleRunner())
        self.assertEqual(gateway.resolved_table_name, "错题题目")


if __name__ == "__main__":
    unittest.main()
