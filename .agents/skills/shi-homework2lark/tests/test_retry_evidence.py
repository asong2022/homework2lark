from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
import retry_evidence as evidence  # noqa: E402


def raw(
    event_id="retry_one",
    *,
    result="incorrect",
    student="学生A",
    number="01",
    at="2026-11-05T12:00:00+08:00",
):
    return {
        "schemaVersion": "retry-feedback-event-v1",
        "eventId": event_id,
        "batch_code": "20261105-01",
        "instance_code": "S001",
        "item_code": "R01",
        "question_id": "problem_one",
        "variant_id": None,
        "student_name": student,
        "student_number": number,
        "observed_response": "把135°判断成锐角",
        "mark_evidence": "红笔圈出135°",
        "teacher_judgment": "仍缺少直角参照",
        "result": result,
        "mastery": None,
        "observed_at": at,
    }


class RetryEvidenceTests(unittest.TestCase):
    def test_duplicate_events_count_once_and_uncertainty_is_not_an_error(self):
        rows = [
            evidence.parse_event(raw(str(i), result=result))
            for i, result in enumerate(
                ("correct", "partial", "incorrect", "uncertain", "not_observed")
            )
        ]
        report = evidence.summarize([*rows, rows[0]])
        self.assertEqual(report["attemptCount"], 5)
        self.assertEqual(report["observedCount"], 3)
        self.assertEqual(report["accuracy"], 1 / 3)
        self.assertEqual(report["incorrect"], 1)
        self.assertEqual(report["uncertain"], 1)
        self.assertEqual(report["notObserved"], 1)
        self.assertEqual(evidence.summarize([rows[3]])["accuracy"], None)

    def test_student_requires_exact_roster_name_and_number_not_instance_code(self):
        rows = [
            evidence.parse_event(raw()),
            evidence.parse_event(raw("other", student="学生B", number="02")),
        ]
        self.assertEqual(len(evidence.for_student(rows, "学生A", "1")), 1)
        self.assertEqual(evidence.for_student(rows, "学生A", "02"), ())
        anonymous = {**raw("anon"), "schemaVersion": 1, "occurred_at": "2026-11-05T12:00:00Z"}
        self.assertEqual(evidence.for_student([evidence.parse_event(anonymous)], "学生A", "01"), ())

    def test_latest_observable_survives_a_later_uncertain_result(self):
        before = evidence.parse_event(raw("before", at="2026-11-04T12:00:00Z"))
        after = evidence.parse_event(raw("after", result="uncertain", at="2026-11-05T12:00:00Z"))
        self.assertEqual(evidence.latest_by_question([after, before])["problem_one"], after)
        self.assertEqual(
            evidence.latest_by_question([after, before], observable_only=True)["problem_one"],
            before,
        )
        self.assertIsNone(after.selection_mastery)

    def test_targets_are_exact_batch_instance_item_links_not_new_diagnoses(self):
        event = evidence.parse_event(raw())
        targets = {
            (event.batch_code, event.instance_code, event.item_code, event.question_id): (
                "概念理解",
                "图形与表征",
            )
        }
        report = evidence.summarize([event], targets)
        self.assertEqual(
            {row["errorCategory"] for row in report["byTargetErrorCategory"]},
            {"概念理解", "图形与表征"},
        )
        self.assertEqual(report["attemptCount"], 1)

    def test_load_deduplicates_and_rejects_conflicting_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            line = json.dumps(raw(), ensure_ascii=False)
            path.write_text(line + "\n" + line + "\n", encoding="utf-8")
            self.assertEqual(len(evidence.load_events(path)), 1)
            path.write_text(line + "\n" + json.dumps(raw(result="correct")), encoding="utf-8")
            with self.assertRaises(evidence.core.SkillError) as captured:
                evidence.load_events(path)
            self.assertEqual(captured.exception.code, "retry_history_conflict")


if __name__ == "__main__":
    unittest.main()
