from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from PIL import Image

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "personal_practice.py"
SPEC = importlib.util.spec_from_file_location("personal_practice", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load personal_practice module")
personal_practice = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = personal_practice
SPEC.loader.exec_module(personal_practice)


def _asset(
    question_id: str,
    *,
    variant_number: int | None = None,
    question: str | None = None,
    answer_lines: int = 0,
    attachment=None,
):
    if variant_number is None:
        return personal_practice.PracticeAsset(
            "original",
            question_id,
            None,
            None,
            question or f"{question_id} 原题",
            answer_lines,
            attachment,
        )
    return personal_practice.PracticeAsset(
        "variant",
        question_id,
        f"variant:v1:{question_id}-{variant_number}",
        variant_number,
        question or f"{question_id} 变式题{variant_number}",
        answer_lines,
        attachment,
    )


def _evidence(
    mastery: str,
    category: str,
    assignment_date: str,
    retry_date: str | None = None,
):
    return personal_practice.MistakeEvidence(
        mastery,
        category,
        date.fromisoformat(assignment_date),
        date.fromisoformat(retry_date) if retry_date else None,
    )


def _bundle(
    question_id: str,
    evidence,
    *,
    variant_count: int = 0,
    question: str | None = None,
    answer_lines: int = 0,
    attachment=None,
):
    return personal_practice.QuestionBundle(
        original=_asset(
            question_id,
            question=question,
            answer_lines=answer_lines,
            attachment=attachment,
        ),
        variants=tuple(
            _asset(question_id, variant_number=index) for index in range(1, variant_count + 1)
        ),
        evidence=tuple(evidence),
    )


class FakeGateway:
    def __init__(self, data, *, image_source: Path | None = None) -> None:
        self.data = data
        self.image_source = image_source
        self.requested_name = None

    def validate_schema(self):
        return {
            "tables": ["错题题目", "错题记录", "变式题"],
            "personalPractice": "ready",
        }

    def load_for_student(self, student_name):
        self.requested_name = student_name
        return self.data

    def materialize_attachment(self, attachment, destination):
        if self.image_source is None:
            raise AssertionError("unexpected attachment download")
        shutil.copyfile(self.image_source, destination)


class PersonalPracticeTests(unittest.TestCase):
    def _roster(self, root: Path, students=None) -> Path:
        path = root / "roster.json"
        path.write_text(
            json.dumps(
                {
                    "students": students
                    or [
                        {"studentNumber": "01", "name": "学生A"},
                        {"studentNumber": "02", "name": "学生B"},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_roster_resolves_anonymous_instance_and_rejects_duplicate_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            roster = personal_practice.load_roster(self._roster(root))
            student = personal_practice.resolve_student(roster, "02")

            self.assertEqual(student.name, "学生B")
            self.assertEqual(student.instance_code, "S002")

            duplicate = self._roster(
                root,
                [
                    {"studentNumber": "01", "name": "学生A"},
                    {"studentNumber": "02", "name": "学生A"},
                ],
            )
            with self.assertRaisesRegex(Exception, "同名学生"):
                personal_practice.load_roster(duplicate)

            duplicate_number = self._roster(
                root,
                [
                    {"studentNumber": "01", "name": "学生A"},
                    {"studentNumber": "01", "name": "学生B"},
                ],
            )
            with self.assertRaisesRegex(Exception, "重复学号"):
                personal_practice.load_roster(duplicate_number)

            with self.assertRaisesRegex(Exception, "没有唯一匹配"):
                personal_practice.resolve_student(roster, "99")

    def test_order_keeps_mastery_priority_then_covers_categories(self) -> None:
        bundles = (
            _bundle("problem_a", [_evidence("需再练", "运算与计算", "2026-07-15")]),
            _bundle("problem_b", [_evidence("需再练", "概念理解", "2026-07-13")]),
            _bundle("problem_c", [_evidence("需再练", "运算与计算", "2026-07-14")]),
            _bundle("problem_d", [_evidence("练习中", "推理与表达", "2026-07-15")]),
        )

        ordered = personal_practice.order_bundles(bundles)

        self.assertEqual(
            [profile.bundle.original.question_id for profile in ordered],
            ["problem_a", "problem_b", "problem_c", "problem_d"],
        )

    def test_recent_retry_is_the_effective_evidence_date(self) -> None:
        bundles = (
            _bundle(
                "problem_retried",
                [_evidence("需再练", "运算与计算", "2026-07-01", "2026-07-15")],
            ),
            _bundle(
                "problem_new_assignment",
                [_evidence("需再练", "运算与计算", "2026-07-14")],
            ),
        )

        ordered = personal_practice.order_bundles(bundles)

        self.assertEqual(ordered[0].bundle.original.question_id, "problem_retried")
        self.assertEqual(ordered[0].evidence_date, date(2026, 7, 15))

    def test_selection_uses_originals_then_round_robin_variants(self) -> None:
        bundles = (
            _bundle(
                "problem_a",
                [_evidence("需再练", "运算与计算", "2026-07-15")],
                variant_count=2,
            ),
            _bundle(
                "problem_b",
                [_evidence("练习中", "概念理解", "2026-07-14")],
                variant_count=2,
            ),
        )

        selected = personal_practice.select_assets(bundles, 5)

        self.assertEqual(
            [(item.asset.question_id, item.asset.variant_number) for item in selected],
            [
                ("problem_a", None),
                ("problem_b", None),
                ("problem_a", 1),
                ("problem_b", 1),
                ("problem_a", 2),
            ],
        )

    def test_selection_does_not_pad_and_excludes_mastered_by_default(self) -> None:
        unresolved = _bundle(
            "problem_open",
            [_evidence("未开始", "其他/待判断", "2026-07-12")],
        )
        mastered = _bundle(
            "problem_done",
            [_evidence("已掌握", "运算与计算", "2026-07-14")],
        )

        selected = personal_practice.select_assets((unresolved, mastered), 6)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].asset.question_id, "problem_open")

        included = personal_practice.select_assets(
            (mastered,),
            1,
            include_mastered=True,
        )
        self.assertEqual(included[0].asset.question_id, "problem_done")

    def test_duplicate_error_evidence_still_produces_one_primary_question(self) -> None:
        bundle = _bundle(
            "problem_same",
            [
                _evidence("练习中", "审题与信息提取", "2026-07-13"),
                _evidence("需再练", "方法与策略", "2026-07-15"),
            ],
        )

        selected = personal_practice.select_assets((bundle,), 4)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].profile.mastery, "需再练")
        self.assertEqual(selected[0].profile.error_category, "方法与策略")

    def test_plan_keeps_items_flat_for_word_auto_flow(self) -> None:
        long_text = "请完整说明你的思考过程。" * 20
        bundles = (
            _bundle(
                "problem_a",
                [_evidence("需再练", "推理与表达", "2026-07-15")],
                question=long_text,
                answer_lines=8,
            ),
            _bundle(
                "problem_b",
                [_evidence("需再练", "概念理解", "2026-07-14")],
                question=long_text,
                answer_lines=8,
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = personal_practice.PersonalPracticeService(
                FakeGateway(personal_practice.PersonalPracticeData(bundles))
            )
            result = service.plan(
                roster_path=self._roster(root),
                student_number="01",
                batch_code="20260715-02",
                question_count=2,
                output_dir=root / "auto-flow",
            )
            manifest = json.loads(
                (root / "auto-flow" / "manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["layout"], "word_auto_flow")
        self.assertNotIn("pages", manifest)
        self.assertEqual([item["itemCode"] for item in manifest["items"]], ["R01", "R02"])

    def test_plan_writes_private_manifest_report_and_downloaded_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_image = root / "source.png"
            Image.new("RGB", (640, 240), "white").save(source_image)
            attachment = personal_practice.AttachmentRef(
                "错题题目",
                "remote_record_key",
                "private_file_token",
                ".png",
                "示例数轴题图",
            )
            data = personal_practice.PersonalPracticeData(
                (
                    _bundle(
                        "problem_image",
                        [_evidence("需再练", "图形与表征", "2026-07-15")],
                        attachment=attachment,
                    ),
                ),
                skipped_invalid_records=2,
            )
            gateway = FakeGateway(data, image_source=source_image)
            service = personal_practice.PersonalPracticeService(gateway)
            destination = root / "personal-output"

            result = service.plan(
                roster_path=self._roster(root),
                student_number="01",
                batch_code="20260715-02",
                question_count=6,
                output_dir=destination,
            )

            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            report = json.loads((destination / "selection.json").read_text(encoding="utf-8"))
            self.assertEqual(gateway.requested_name, "学生A")
            self.assertEqual(result["selected"], 1)
            self.assertEqual(manifest["manifestVersion"], "personal-practice-v2")
            self.assertEqual(manifest["student"]["instanceCode"], "S001")
            self.assertEqual(
                manifest["items"][0]["stemImage"]["path"],
                "images/R01.png",
            )
            self.assertTrue((destination / "images" / "R01.png").is_file())
            self.assertEqual(report["selectedQuestionCount"], 1)
            self.assertEqual(report["skippedInvalidRecords"], 2)
            self.assertNotIn("学生A", "20260715-02-S001-P1")
            self.assertNotIn("学生A", json.dumps(result, ensure_ascii=False))
            self.assertNotIn('"01"', json.dumps(result, ensure_ascii=False))

    def test_plan_never_overwrites_an_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "existing"
            destination.mkdir()
            service = personal_practice.PersonalPracticeService(
                FakeGateway(
                    personal_practice.PersonalPracticeData(
                        (
                            _bundle(
                                "problem_a",
                                [_evidence("需再练", "运算与计算", "2026-07-15")],
                            ),
                        )
                    )
                )
            )

            with self.assertRaisesRegex(Exception, "输出目录已存在"):
                service.plan(
                    roster_path=self._roster(root),
                    student_number="01",
                    batch_code="20260715-02",
                    question_count=1,
                    output_dir=destination,
                )

    def test_student_filter_is_exact_multiselect_intersection(self) -> None:
        self.assertEqual(
            personal_practice.student_filter("学生A"),
            {
                "logic": "and",
                "conditions": [["对应学生", "intersects", ["学生A"]]],
            },
        )

    def test_lark_gateway_skips_names_that_are_not_multiselect_options(self) -> None:
        gateway = object.__new__(personal_practice.LarkPersonalPracticeGateway)
        gateway._schema_result = {
            "tables": ["错题题目", "错题记录", "变式题"],
            "personalPractice": "ready",
        }
        gateway._group_student_options = frozenset(("学生A",))

        result = gateway.load_for_student("尚无错题的学生")

        self.assertEqual(result, personal_practice.PersonalPracticeData(()))

    def test_attachment_download_uses_relative_cli_temp_and_caches_bytes(self) -> None:
        class FakeRunner:
            def __init__(self) -> None:
                self.calls = 0

            def run(self, args, *, retry_read=False):
                self.calls += 1
                output = Path(args[args.index("--output") + 1])
                if output.is_absolute():
                    raise AssertionError("lark-cli output must be relative")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"image-bytes")
                return {}

        class FakeTableGateway:
            def _context(self):
                return "base-token", "table-id"

        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            gateway = personal_practice.LarkPersonalPracticeGateway(runner)
            gateway.questions = FakeTableGateway()
            attachment = personal_practice.AttachmentRef(
                "错题题目",
                "record-id",
                "file-token",
                ".png",
                "题图",
            )
            first = Path(temporary).resolve() / "first.png"
            second = Path(temporary).resolve() / "second.png"

            gateway.materialize_attachment(attachment, first)
            gateway.materialize_attachment(attachment, second)

            self.assertEqual(runner.calls, 1)
            self.assertEqual(first.read_bytes(), b"image-bytes")
            self.assertEqual(second.read_bytes(), b"image-bytes")


if __name__ == "__main__":
    unittest.main()
