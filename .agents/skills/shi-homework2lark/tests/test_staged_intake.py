from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "staged_intake.py"
SPEC = importlib.util.spec_from_file_location("staged_intake", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load staged_intake module")
staged_intake = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = staged_intake
SPEC.loader.exec_module(staged_intake)


class StagedIntakeTests(unittest.TestCase):
    def _json(self, path: Path, value) -> Path:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def _image(self, path: Path, color: str = "white") -> Path:
        Image.new("RGB", (320, 480), color).save(path)
        return path

    def _roster(self, root: Path) -> Path:
        return self._json(
            root / "roster.json",
            {
                "students": [
                    {"studentNumber": "01", "name": "学生甲"},
                    {"studentNumber": "02", "name": "学生乙"},
                    {"studentNumber": "03", "name": "学生丙"},
                    {"studentNumber": "04", "name": "学生丁"},
                ]
            },
        )

    def _template(self, root: Path) -> Path:
        page1 = self._image(root / "blank-1.png")
        page2 = self._image(root / "blank-2.png")
        return self._json(
            root / "template.json",
            {
                "pages": [
                    {"pageNumber": 1, "path": str(page1.resolve())},
                    {"pageNumber": 2, "path": str(page2.resolve())},
                ]
            },
        )

    def _start(self, root: Path, *, budget: int = 4) -> Path:
        campaign = root / "campaign"
        result = staged_intake.start_campaign(
            roster_path=self._roster(root),
            assignment_code="20260715-06",
            template_path=self._template(root),
            max_pages_per_batch=budget,
            output_dir=campaign,
        )
        self.assertEqual(result["recommendedStudentsPerBatch"], budget // 2)
        return campaign

    def _submission(self, root: Path, numbers=("01", "02")) -> Path:
        submissions = []
        for number in numbers:
            page1 = self._image(root / f"student-{number}-1.jpg", "lightgray")
            page2 = self._image(root / f"student-{number}-2.jpg", "lightblue")
            submissions.append(
                {
                    "studentNumber": number,
                    "pages": [
                        {"pageNumber": 1, "path": str(page1.resolve())},
                        {"pageNumber": 2, "path": str(page2.resolve())},
                    ],
                }
            )
        file_name = f"submission-{'-'.join(numbers)}.json"
        return self._json(root / file_name, {"submissions": submissions})

    def _result(self, root: Path, *, observed: str = "70") -> Path:
        return self._json(
            root / f"result-{observed}.json",
            {
                "students": [
                    {
                        "studentNumber": "01",
                        "findings": [
                            {
                                "pageNumber": 1,
                                "questionId": "problem_02",
                                "questionNumber": "2",
                                "observedResponse": observed,
                                "markEvidence": "红笔划线并打叉",
                                "result": "incorrect",
                                "note": "",
                            }
                        ],
                    },
                    {"studentNumber": "02", "findings": []},
                ]
            },
        )

    def _empty_result(self, root: Path, batch_id: str, number: str) -> Path:
        return self._json(
            root / f"result-{batch_id}.json",
            {"students": [{"studentNumber": number, "findings": []}]},
        )

    def test_two_page_campaign_runs_in_two_student_batches_and_exports_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = self._start(root)

            added = staged_intake.add_batch(
                campaign_dir=campaign,
                input_path=self._submission(root),
            )
            self.assertEqual(added["batchId"], "B01")
            self.assertEqual(added["students"], 2)
            self.assertEqual(added["pages"], 4)
            self.assertTrue(
                (campaign / "batches" / "B01" / "sources" / "S001" / "P1.jpg").is_file()
            )

            status = staged_intake.campaign_status(campaign_dir=campaign)
            self.assertEqual(status["studentsAdded"], 2)
            self.assertEqual(status["studentsRemaining"], 2)
            self.assertEqual(status["pendingBatches"], 1)

            completed = staged_intake.complete_batch(
                campaign_dir=campaign,
                batch_id="B01",
                input_path=self._result(root),
            )
            self.assertEqual(completed["findings"], 1)
            unchanged = staged_intake.complete_batch(
                campaign_dir=campaign,
                batch_id="B01",
                input_path=self._result(root),
            )
            self.assertEqual(unchanged["status"], "no_change")

            export_path = root / "partial-export.json"
            exported = staged_intake.export_results(
                campaign_dir=campaign,
                output_path=export_path,
            )
            export = json.loads(export_path.read_text(encoding="utf-8"))
            self.assertFalse(exported["isComplete"])
            self.assertEqual(exported["studentsCompleted"], 2)
            self.assertEqual(exported["studentsRemaining"], 2)
            self.assertEqual(export["students"][0]["findings"][0]["observedResponse"], "70")
            self.assertEqual(export["students"][1]["findings"], [])

            campaign_text = (campaign / "campaign.json").read_text(encoding="utf-8")
            batch_text = (campaign / "batches" / "B01" / "batch.json").read_text(encoding="utf-8")
            self.assertNotIn(str(root.resolve()), campaign_text)
            self.assertNotIn(str(root.resolve()), batch_text)

    def test_page_budget_rejects_too_many_students_without_creating_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = self._start(root)
            submission = self._submission(root, ("01", "02", "03"))

            with self.assertRaisesRegex(Exception, "超过活动上限"):
                staged_intake.add_batch(campaign_dir=campaign, input_path=submission)

            self.assertFalse((campaign / "batches" / "B01").exists())
            self.assertEqual(staged_intake.campaign_status(campaign_dir=campaign)["batches"], 0)

    def test_rejects_missing_pages_and_duplicate_students_across_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = self._start(root)
            page = self._image(root / "only-one-page.jpg")
            missing = self._json(
                root / "missing.json",
                {
                    "submissions": [
                        {
                            "studentNumber": "01",
                            "pages": [{"pageNumber": 1, "path": str(page.resolve())}],
                        }
                    ]
                },
            )
            with self.assertRaisesRegex(Exception, "完整页面"):
                staged_intake.add_batch(campaign_dir=campaign, input_path=missing)

            staged_intake.add_batch(
                campaign_dir=campaign,
                input_path=self._submission(root, ("01",)),
            )
            with self.assertRaisesRegex(Exception, "重复加入"):
                staged_intake.add_batch(
                    campaign_dir=campaign,
                    input_path=self._submission(root, ("01",)),
                )

    def test_completed_batch_cannot_be_overwritten_with_different_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = self._start(root)
            staged_intake.add_batch(
                campaign_dir=campaign,
                input_path=self._submission(root),
            )
            staged_intake.complete_batch(
                campaign_dir=campaign,
                batch_id="B01",
                input_path=self._result(root, observed="70"),
            )

            with self.assertRaisesRegex(Exception, "不能覆盖"):
                staged_intake.complete_batch(
                    campaign_dir=campaign,
                    batch_id="B01",
                    input_path=self._result(root, observed="65"),
                )

            saved = json.loads(
                (campaign / "batches" / "B01" / "results.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["students"][0]["findings"][0]["observedResponse"], "70")

    def test_concurrent_batch_completion_preserves_both_campaign_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = self._start(root)
            staged_intake.add_batch(
                campaign_dir=campaign,
                input_path=self._submission(root, ("01",)),
            )
            staged_intake.add_batch(
                campaign_dir=campaign,
                input_path=self._submission(root, ("02",)),
            )
            result_one = self._empty_result(root, "B01", "01")
            result_two = self._empty_result(root, "B02", "02")
            real_load = staged_intake._load_campaign
            read_barrier = threading.Barrier(2)

            def synchronized_load(path: Path):
                loaded = real_load(path)
                with contextlib.suppress(threading.BrokenBarrierError):
                    read_barrier.wait(timeout=0.25)
                return loaded

            with (
                patch.object(staged_intake, "_load_campaign", side_effect=synchronized_load),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                futures = (
                    executor.submit(
                        staged_intake.complete_batch,
                        campaign_dir=campaign,
                        batch_id="B01",
                        input_path=result_one,
                    ),
                    executor.submit(
                        staged_intake.complete_batch,
                        campaign_dir=campaign,
                        batch_id="B02",
                        input_path=result_two,
                    ),
                )
                for future in futures:
                    self.assertEqual(future.result()["status"], "completed")

            saved = json.loads((campaign / "campaign.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {batch["batchId"]: batch["status"] for batch in saved["batches"]},
                {"B01": "completed", "B02": "completed"},
            )

    def test_rejects_inferred_cause_fields_in_observation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = self._start(root)
            staged_intake.add_batch(
                campaign_dir=campaign,
                input_path=self._submission(root),
            )
            raw = json.loads(self._result(root).read_text(encoding="utf-8"))
            raw["students"][0]["findings"][0]["errorCause"] = "粗心"
            invalid = self._json(root / "inferred-cause.json", raw)

            with self.assertRaisesRegex(Exception, "已观察事实"):
                staged_intake.complete_batch(
                    campaign_dir=campaign,
                    batch_id="B01",
                    input_path=invalid,
                )


if __name__ == "__main__":
    unittest.main()
