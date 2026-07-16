from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = SKILL_ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import base_metadata  # noqa: E402
import homework2lark  # noqa: E402


class MemoryMetadataGateway:
    def __init__(self) -> None:
        self.page = homework2lark.BaseRecord(
            "page_record",
            {
                "页面名称": "",
                "时间": None,
                "年级": [],
                "页码": "",
                "单元": None,
                "课题名": "",
                "错题来源": [],
                "页面主知识点": "",
            },
        )
        self.question = homework2lark.BaseRecord(
            "question_record",
            {
                "时间": None,
                "年级": [],
                "页码": "",
                "错题来源": [],
                "题号": "",
                "题目名称": "",
                "分区标题": "",
                "题型": [],
                "核心素养": [],
                "对应知识点": "",
                "图表说明": "",
                "标准答案": "",
                "答案备注": "",
                "设计意图": "",
            },
        )
        self.page_patches: list[dict[str, base_metadata.JSONValue]] = []
        self.question_patches: list[dict[str, base_metadata.JSONValue]] = []

    def load(self, problem_id: str) -> base_metadata.EnrichmentRows:
        if problem_id != "problem_alpha":
            raise AssertionError("unexpected problem")
        return base_metadata.EnrichmentRows(
            page=homework2lark.BaseRecord(self.page.record_id, copy.deepcopy(self.page.fields)),
            question=homework2lark.BaseRecord(
                self.question.record_id, copy.deepcopy(self.question.fields)
            ),
        )

    def patch_page(self, record_id: str, patch: dict[str, base_metadata.JSONValue]) -> None:
        self.assert_record(record_id, self.page.record_id)
        self.page_patches.append(copy.deepcopy(patch))
        self.page.fields.update(copy.deepcopy(patch))
        for name, value in patch.items():
            if name in base_metadata.QUESTION_LOOKUP_FIELDS:
                self.question.fields[name] = copy.deepcopy(value)

    def patch_question(self, record_id: str, patch: dict[str, base_metadata.JSONValue]) -> None:
        self.assert_record(record_id, self.question.record_id)
        self.question_patches.append(copy.deepcopy(patch))
        for name, value in patch.items():
            self.question.fields[name] = [value] if name == "题型" else copy.deepcopy(value)

    def assert_record(self, actual: str, expected: str) -> None:
        if actual != expected:
            raise AssertionError(f"expected {expected}, got {actual}")


def payload() -> dict[str, base_metadata.JSONValue]:
    return {
        "problemId": "problem_alpha",
        "page": {
            "页面名称": "综合应用与图形操作（第116页）",
            "时间": "2026-07-14",
            "年级": "四年级",
            "页码": "116",
            "课题名": "综合应用与图形操作",
            "错题来源": "教材",
        },
        "question": {
            "题号": "13",
            "题目名称": "买几送几问题",
            "题型": "应用题",
            "核心素养": ["运算能力", "模型意识", "应用意识"],
            "对应知识点": "乘法应用；周期优惠；总价计算",
            "标准答案": "14400元",
            "设计意图": "理解买几送几中的实际付费箱数，并建立总价模型。",
        },
        "note": "AI 根据完整题图整理，等待教师复核。",
    }


def live_schema() -> dict[str, base_metadata._TableContext]:
    page_fields = {
        name: homework2lark.BaseField(
            f"page_{index}",
            name,
            field_type,
            base_metadata.intake.PAGE_SOURCE_OPTIONS
            if name == "错题来源"
            else base_metadata.intake.GRADE_OPTIONS
            if name == "年级"
            else frozenset(),
        )
        for index, (name, field_type) in enumerate(base_metadata.PAGE_FIELD_TYPES.items(), start=1)
    }
    question_fields = {
        base_metadata.QUESTION_ID_FIELD: homework2lark.BaseField(
            "question_id", base_metadata.QUESTION_ID_FIELD, "text", frozenset()
        ),
        base_metadata.QUESTION_PAGE_LINK_FIELD: homework2lark.BaseField(
            "question_page", base_metadata.QUESTION_PAGE_LINK_FIELD, "link", frozenset()
        ),
    }
    for index, (name, source_name) in enumerate(
        base_metadata.QUESTION_LOOKUP_FIELDS.items(), start=1
    ):
        question_fields[name] = homework2lark.BaseField(
            f"lookup_{index}",
            name,
            "lookup",
            frozenset(),
            base_metadata.PAGE_TABLE,
            page_fields[source_name].field_id,
        )
    for index, (name, field_type) in enumerate(base_metadata.QUESTION_FIELD_TYPES.items(), start=1):
        question_fields[name] = homework2lark.BaseField(
            f"question_{index}",
            name,
            field_type,
            base_metadata.intake.QUESTION_TYPE_OPTIONS
            if name == "题型"
            else base_metadata.intake.CORE_LITERACY_OPTIONS
            if name == "核心素养"
            else frozenset(),
        )
    return {
        base_metadata.PAGE_TABLE: base_metadata._TableContext("page", page_fields),
        base_metadata.QUESTION_TABLE: base_metadata._TableContext("question", question_fields),
    }


class BaseMetadataServiceTest(unittest.TestCase):
    def test_preview_reports_only_field_names_and_does_not_write(self) -> None:
        gateway = MemoryMetadataGateway()
        result = base_metadata.BaseMetadataService(gateway).preview(payload()).public()

        self.assertEqual(result["status"], "ready")
        self.assertEqual(
            result["page"]["willWrite"],
            ["年级", "时间", "课题名", "错题来源", "页码", "页面名称"],
        )
        self.assertEqual(
            set(result["question"]["willWrite"]),
            {
                "标准答案",
                "题号",
                "题型",
                "题目名称",
                "对应知识点",
                "核心素养",
                "设计意图",
            },
        )
        self.assertNotIn("14400元", str(result))
        self.assertNotIn("促销周期", str(result))
        self.assertEqual(gateway.page_patches, [])
        self.assertEqual(gateway.question_patches, [])

    def test_numeric_and_publisher_fallback_titles_can_be_replaced(self) -> None:
        gateway = MemoryMetadataGateway()
        gateway.page.fields["页面名称"] = "3"
        gateway.question.fields["题目名称"] = "待整理题目·超市开展促销活动"

        plan = base_metadata.BaseMetadataService(gateway).preview(payload())

        self.assertEqual(plan.page.patch["页面名称"], "综合应用与图形操作（第116页）")
        self.assertEqual(plan.question.patch["题目名称"], "买几送几问题")

    def test_conflicting_nonempty_value_blocks_all_writes(self) -> None:
        gateway = MemoryMetadataGateway()
        gateway.page.fields["页码"] = "115"
        gateway.question.fields["页码"] = "115"
        service = base_metadata.BaseMetadataService(gateway)

        preview = service.preview(payload()).public()
        self.assertEqual(preview["status"], "conflict")
        self.assertEqual(preview["page"]["conflicts"], ["页码"])
        with self.assertRaises(base_metadata.intake.SkillError) as captured:
            service.apply(payload())

        self.assertEqual(captured.exception.code, "metadata_conflict")
        self.assertEqual(gateway.page_patches, [])
        self.assertEqual(gateway.question_patches, [])

    def test_apply_is_read_back_and_second_run_is_idempotent(self) -> None:
        gateway = MemoryMetadataGateway()
        service = base_metadata.BaseMetadataService(gateway)

        first = service.apply(payload())
        second = service.apply(payload())

        self.assertEqual(first["status"], "applied")
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(len(gateway.page_patches), 1)
        self.assertEqual(len(gateway.question_patches), 1)

    def test_nonempty_metadata_cannot_be_silently_changed(self) -> None:
        gateway = MemoryMetadataGateway()
        gateway.page.fields.update(payload()["page"])
        for lookup_name in base_metadata.QUESTION_LOOKUP_FIELDS:
            gateway.question.fields[lookup_name] = payload()["page"][lookup_name]
        gateway.question.fields.update(payload()["question"])
        changed = payload()
        changed["question"] = dict(changed["question"])
        changed["question"]["标准答案"] = "另一个答案"

        plan = base_metadata.BaseMetadataService(gateway).preview(changed)

        self.assertIn("标准答案", plan.question.conflicts)

    def test_live_schema_rejects_missing_select_options(self) -> None:
        tables = live_schema()
        base_metadata._validate_live_schema(tables)
        current = tables[base_metadata.QUESTION_TABLE].fields["题型"]
        tables[base_metadata.QUESTION_TABLE].fields["题型"] = homework2lark.BaseField(
            current.field_id, current.name, current.field_type, frozenset(("计算题",))
        )

        with self.assertRaises(base_metadata.intake.SkillError) as captured:
            base_metadata._validate_live_schema(tables)

        self.assertEqual(captured.exception.code, "schema_mismatch")

    def test_live_schema_rejects_lookup_from_wrong_page_field(self) -> None:
        tables = live_schema()
        current = tables[base_metadata.QUESTION_TABLE].fields["页码"]
        tables[base_metadata.QUESTION_TABLE].fields["页码"] = homework2lark.BaseField(
            current.field_id,
            current.name,
            current.field_type,
            current.options,
            base_metadata.PAGE_TABLE,
            tables[base_metadata.PAGE_TABLE].fields["课题名"].field_id,
        )

        with self.assertRaises(base_metadata.intake.SkillError) as captured:
            base_metadata._validate_live_schema(tables)

        self.assertEqual(captured.exception.code, "schema_mismatch")

    def test_preview_rejects_lookup_value_different_from_linked_page(self) -> None:
        gateway = MemoryMetadataGateway()
        gateway.page.fields["页码"] = "116"
        gateway.question.fields["页码"] = "112"

        with self.assertRaises(base_metadata.intake.SkillError) as captured:
            base_metadata.BaseMetadataService(gateway).preview(payload())

        self.assertEqual(captured.exception.code, "schema_mismatch")


if __name__ == "__main__":
    unittest.main()
