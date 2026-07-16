from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("homework_workflow", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load workflow module")
workflow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)


class WorkflowTests(unittest.TestCase):
    def test_choices_require_user_and_have_three_fixed_modes(self) -> None:
        result = workflow.list_choices()

        self.assertTrue(result["selectionRequired"])
        self.assertEqual(result["decidedBy"], "user")
        self.assertEqual(
            [item["id"] for item in result["choices"]],
            [
                "teacher_selected",
                "anonymous_corrected",
                "identified_corrected",
            ],
        )

    def test_ai_cannot_start_without_a_user_mode(self) -> None:
        for value in ("", "auto", "recommend", "ai_decides"):
            with self.subTest(value=value), self.assertRaises(workflow.WorkflowError):
                workflow.build_state(value)

    def test_numeric_and_label_choices_persist_decided_by_user(self) -> None:
        anonymous = workflow.build_state("2")
        identified = workflow.build_state("实名绑定统计")

        self.assertEqual(anonymous["collectionMode"], "anonymous_corrected")
        self.assertNotIn("私有学号姓名名单", anonymous["requiredInputs"])
        self.assertEqual(identified["collectionMode"], "identified_corrected")
        self.assertIn("私有学号姓名名单", identified["requiredInputs"])
        self.assertEqual(identified["decidedBy"], "user")

    def test_start_accepts_explicit_absolute_output_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "workflow.json"
            code = workflow.main(
                [
                    "start",
                    "--collection-mode",
                    "1",
                    "--output",
                    str(output),
                ]
            )
            saved = json.loads(output.read_text(encoding="utf-8"))
            second = workflow.main(
                [
                    "start",
                    "--collection-mode",
                    "1",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(second, 2)
        self.assertEqual(saved["collectionMode"], "teacher_selected")
        self.assertEqual(saved["decidedBy"], "user")

    def test_tampered_identity_policy_is_rejected(self) -> None:
        state = workflow.build_state("3")
        state["identityPolicy"] = "AI 自动猜姓名"

        with self.assertRaises(workflow.WorkflowError):
            workflow.validate_state(state)


if __name__ == "__main__":
    unittest.main()
