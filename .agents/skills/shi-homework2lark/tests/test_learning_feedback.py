from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = load("homework2lark")
feedback = load("learning_feedback")


class MemoryGateway:
    def __init__(self) -> None:
        field_types = {
            "系统题目ID": "text",
            "题目名称": "text",
            core.COLLECTION_ORDER_FIELD: "auto_number",
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
            core.TYPICAL_ERROR_FIELD: "lookup",
            core.ERROR_PATTERN_FIELD: "lookup",
            core.ERROR_CAUSE_SUMMARY_FIELD: "text",
            **core.EXPECTED_FIELD_TYPES,
            **feedback.FEEDBACK_FIELD_TYPES,
        }
        fields = {}
        for index, (name, field_type) in enumerate(field_types.items(), start=1):
            options = frozenset()
            if name == "掌握状态":
                options = feedback.MASTERY_OPTIONS
            elif name == "核心素养":
                options = core.CORE_LITERACY_OPTIONS
            fields[name] = core.BaseField(f"fld_{index}", name, field_type, options)
        views = {
            name: core.BaseView(f"view_{index}", name)
            for index, name in enumerate(core.EXPECTED_VIEW_FILTERS, start=1)
        }
        filters = {
            name: {"logic": "and", "conditions": [list(item) for item in conditions]}
            for name, conditions in core.EXPECTED_VIEW_FILTERS.items()
        }
        self._schema = core.BaseSchema(fields, views, filters)
        values = {name: None for name in fields}
        values.update(
            {
                "系统题目ID": "problem_alpha",
                "题目名称": "折135度角问题",
                core.COLLECTION_ORDER_FIELD: "1",
                "图片题目": [{"file_token": "private"}],
                "题干图片": [],
                "题干文本": "一道完整题",
                "本地修订版本": 1,
                "已审核时间": "2026-07-14 10:30:00",
                core.REVERSE_VARIANT_LINK_FIELD: [{"id": "variant_1"}],
                core.TYPICAL_ERROR_FIELD: "原始真实作答保持不变",
            }
        )
        self.record = core.BaseRecord("rec_1", values)

    def schema(self):
        return self._schema

    def get_record(self, record_id, fields):
        if record_id != "rec_1":
            raise core.SkillError("record_not_found", "missing")
        return core.BaseRecord(
            record_id,
            {name: copy.deepcopy(self.record.fields.get(name)) for name in fields},
        )

    def patch_record(self, record_id, patch):
        del record_id
        for name, value in patch.items():
            self.record.fields[name] = [value] if name == "掌握状态" else copy.deepcopy(value)

    def list_records(self, fields, **kwargs):
        del kwargs
        return [self.get_record("rec_1", fields)]

    def download_attachments(self, record_id, output_dir):
        del record_id, output_dir

    def upload_attachment(self, record_id, field_name, file_path):
        del record_id, field_name, file_path


def payload(**overrides):
    data = {
        "questionId": "problem_alpha",
        "variantNumber": 1,
        "observedResponse": "把135度判断成锐角。",
        "teacherJudgment": "缺少直角参照。",
        "result": "incorrect",
        "mastery": "需再练",
        "summary": "变式1仍把135度判断成锐角，需加入直角参照。",
        "occurredAt": "2026-07-14T10:30:00+08:00",
    }
    data.update(overrides)
    return feedback.validate_feedback_payload(data)


class LearningFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.gateway = MemoryGateway()
        self.service = feedback.FeedbackService(self.gateway)

    def test_preview_is_read_only_and_separates_evidence(self):
        before = copy.deepcopy(self.gateway.record.fields)
        result = self.service.preview("rec_1", payload())
        self.assertTrue(result["willAppendLocalHistory"])
        self.assertFalse(result["willOverwriteTypicalStudentError"])
        self.assertEqual(self.gateway.record.fields, before)

    def test_record_is_idempotent_locally_and_preserves_original_error(self):
        original = self.gateway.record.fields[core.TYPICAL_ERROR_FIELD]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            relative = os.path.relpath(Path(tmp) / "events.jsonl", Path.cwd())
            first = self.service.record("rec_1", payload(), relative)
            second = self.service.record("rec_1", payload(), relative)
            lines = (Path.cwd() / relative).read_text(encoding="utf-8").splitlines()
        self.assertTrue(first["historyAppended"])
        self.assertFalse(second["historyAppended"])
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["eventId"], first["eventId"])
        self.assertEqual(self.gateway.record.fields[core.TYPICAL_ERROR_FIELD], original)
        self.assertEqual(self.gateway.record.fields["掌握状态"], ["需再练"])

    def test_older_event_is_appended_without_regressing_current_projection(self):
        self.gateway.record.fields["掌握状态"] = ["已掌握"]
        self.gateway.record.fields["最近再练时间"] = "2026-07-16 10:30:00"
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            relative = os.path.relpath(Path(tmp) / "events.jsonl", Path.cwd())
            result = self.service.record(
                "rec_1",
                payload(occurredAt="2026-07-15T10:30:00+08:00", mastery="需再练"),
                relative,
            )
            lines = (Path.cwd() / relative).read_text(encoding="utf-8").splitlines()

        self.assertTrue(result["historyAppended"])
        self.assertFalse(result["baseProjectionUpdated"])
        self.assertEqual(result["mastery"], "已掌握")
        self.assertEqual(len(lines), 1)
        self.assertEqual(self.gateway.record.fields["掌握状态"], ["已掌握"])
        self.assertEqual(self.gateway.record.fields["最近再练时间"], "2026-07-16 10:30:00")

    def test_rejects_identity_fields_and_missing_observed_response(self):
        with self.assertRaises(feedback.core.SkillError):
            feedback.validate_feedback_payload(
                {
                    **{
                        "questionId": "problem_alpha",
                        "observedResponse": "作答",
                        "teacherJudgment": "",
                        "result": "incorrect",
                        "mastery": "需再练",
                        "summary": "摘要",
                        "occurredAt": "2026-07-14T10:30:00+08:00",
                    },
                    "studentName": "不应出现",
                }
            )
        with self.assertRaisesRegex(feedback.core.SkillError, "observedResponse"):
            feedback.validate_feedback_payload(
                {
                    "questionId": "problem_alpha",
                    "observedResponse": "",
                    "teacherJudgment": "",
                    "result": "incorrect",
                    "mastery": "需再练",
                    "summary": "摘要",
                    "occurredAt": "2026-07-14T10:30:00+08:00",
                }
            )


if __name__ == "__main__":
    unittest.main()
