from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "class_practice.py"
class_practice = None
personal_practice = None


def _load_modules() -> None:
    global class_practice, personal_practice
    spec = importlib.util.spec_from_file_location("class_practice", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load class_practice module")
    class_practice = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = class_practice
    spec.loader.exec_module(class_practice)
    personal_practice = class_practice.personal_practice


def _data(question_id: str | None):
    if question_id is None:
        return personal_practice.PersonalPracticeData(())
    asset = personal_practice.PracticeAsset(
        "original",
        question_id,
        None,
        None,
        f"{question_id} 题干",
        0,
    )
    evidence = personal_practice.MistakeEvidence(
        "需再练",
        "运算与计算",
        date(2026, 7, 15),
    )
    return personal_practice.PersonalPracticeData(
        (personal_practice.QuestionBundle(asset, (), (evidence,)),)
    )


class FakeGateway:
    def __init__(self, data_by_name) -> None:
        self.data_by_name = data_by_name
        self.loaded_names: list[str] = []

    def validate_schema(self):
        return {"tables": ["错题题目", "错题记录", "变式题"]}

    def load_for_student(self, student_name):
        self.loaded_names.append(student_name)
        return self.data_by_name[student_name]

    def materialize_attachment(self, attachment, destination):
        raise AssertionError("unexpected attachment")


class ClassPracticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _load_modules()

    def _roster(self, root: Path) -> Path:
        path = root / "private-roster.json"
        path.write_text(
            json.dumps(
                {
                    "students": [
                        {"studentNumber": "01", "name": "学生甲"},
                        {"studentNumber": "02", "name": "学生乙"},
                        {"studentNumber": "03", "name": "学生丙"},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def _service(self, gateway, builder=None):
        kwargs = {} if builder is None else {"document_builder": builder}
        return class_practice.ClassPracticeService(
            personal_practice.PersonalPracticeService(gateway),
            **kwargs,
        )

    def test_builds_full_roster_and_skips_empty_students_without_blank_word(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            roster = self._roster(root)
            gateway = FakeGateway(
                {
                    "学生甲": _data("problem_a"),
                    "学生乙": _data(None),
                    "学生丙": _data("problem_c"),
                }
            )

            def fake_builder(_manifest, output):
                output.write_bytes(b"docx")

            output = root / "class-output"
            result = self._service(gateway, fake_builder).build(
                roster_path=roster,
                batch_code="20260715-03",
                question_count=6,
                output_dir=output,
            )

            summary = json.loads((output / "batch-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(result["requestedStudents"], 3)
            self.assertEqual(result["generatedStudents"], 2)
            self.assertEqual(result["studentsWithoutEligibleItems"], 1)
            self.assertEqual(result["layout"], "word_auto_flow")
            self.assertEqual(summary["manifestVersion"], "class-personal-practice-v2")
            self.assertEqual(summary["layout"], "word_auto_flow")
            self.assertNotIn("worksheetPageCount", summary)
            self.assertTrue((output / "students" / "S001" / "S001-个人练习纸.docx").is_file())
            self.assertFalse((output / "students" / "S002").exists())
            self.assertTrue((output / "students" / "S003" / "S003-个人练习纸.docx").is_file())
            self.assertEqual(summary["students"][1]["status"], "no_eligible_items")
            self.assertEqual(gateway.loaded_names, ["学生甲", "学生乙", "学生丙"])
            public_result = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("学生甲", public_result)
            self.assertNotIn('"01"', public_result)
            csv_bytes = (output / "班级个人练习清单.csv").read_bytes()
            self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))

    def test_subset_keeps_instance_code_from_full_roster(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            roster = self._roster(root)
            gateway = FakeGateway(
                {
                    "学生甲": _data("problem_a"),
                    "学生乙": _data("problem_b"),
                    "学生丙": _data("problem_c"),
                }
            )

            def fake_builder(_manifest, output):
                output.write_bytes(b"docx")

            output = root / "subset"
            self._service(gateway, fake_builder).build(
                roster_path=roster,
                batch_code="20260715-04",
                question_count=1,
                output_dir=output,
                student_numbers=("03",),
            )

            manifest = json.loads(
                (output / "students" / "S003" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["student"]["instanceCode"], "S003")
            self.assertEqual(gateway.loaded_names, ["学生丙"])

    def test_technical_failure_removes_the_entire_new_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            roster = self._roster(root)
            gateway = FakeGateway(
                {
                    "学生甲": _data("problem_a"),
                    "学生乙": _data("problem_b"),
                    "学生丙": _data("problem_c"),
                }
            )
            calls = 0

            def failing_builder(_manifest, output):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("simulated renderer failure")
                output.write_bytes(b"docx")

            output = root / "failed-batch"
            with self.assertRaisesRegex(RuntimeError, "renderer failure"):
                self._service(gateway, failing_builder).build(
                    roster_path=roster,
                    batch_code="20260715-05",
                    question_count=1,
                    output_dir=output,
                )

            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".failed-batch.tmp-*")), [])

    def test_rejects_duplicate_or_unknown_subset_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            roster = personal_practice.load_roster(self._roster(Path(temporary)))
            with self.assertRaisesRegex(Exception, "不能为空或重复"):
                class_practice._select_students(roster, ("01", "01"))
            with self.assertRaisesRegex(Exception, "无法唯一匹配"):
                class_practice._select_students(roster, ("99",))


if __name__ == "__main__":
    unittest.main()
