from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "retry_batch.py"
SPEC = importlib.util.spec_from_file_location("homework_retry_batch", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load retry_batch module")
retry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = retry
SPEC.loader.exec_module(retry)


def manifest(instance: str = "S001", name: str = "学生甲", number: str = "01") -> dict:
    return {
        "batchCode": "20260715-01",
        "manifestVersion": "personal-practice-v2",
        "student": {
            "name": name,
            "studentNumber": number,
            "instanceCode": instance,
        },
        "items": [
            {
                "itemCode": "R01",
                "question": "原题一",
                "answerLines": 1,
                "source": {"type": "original", "questionId": "problem_one"},
            },
            {
                "itemCode": "R02",
                "question": "变式题二",
                "answerLines": 2,
                "source": {
                    "type": "variant",
                    "questionId": "problem_two",
                    "variantId": "variant:v1:two:1",
                },
            },
        ],
    }


def observations() -> dict:
    return {
        "observedAt": "2026-07-15T20:00:00+08:00",
        "pages": [
            {
                "pageCode": "20260715-01-S001-P1",
                "items": [
                    {
                        "itemNumber": 1,
                        "observedResponse": "70",
                        "markEvidence": "红笔打叉",
                        "result": "incorrect",
                    },
                    {
                        "itemNumber": 2,
                        "observedResponse": "135°",
                        "markEvidence": "红笔打勾",
                        "result": "correct",
                    },
                ],
            }
        ],
    }


class RetryBatchTests(unittest.TestCase):
    def test_event_id_is_stable_across_roster_name_corrections(self) -> None:
        # 同一份练习、同一次观察：名单里姓名/学号被更正后重跑，
        # 事件 ID 必须不变（Sxxx 才是身份），否则会追加重复事件行。
        plans = []
        for name, number in (("学生甲", "01"), ("学生甲改", "0001")):
            with tempfile.TemporaryDirectory() as temp_dir:
                manifest_path = Path(temp_dir) / "manifest.json"
                manifest_path.write_text(
                    json.dumps(manifest(name=name, number=number), ensure_ascii=False),
                    encoding="utf-8",
                )
                plans.append(retry.build_plan(manifest_path, observations()))
        first_ids = [event["eventId"] for event in plans[0]["events"]]
        second_ids = [event["eventId"] for event in plans[1]["events"]]
        self.assertEqual(first_ids, second_ids)

        # 观察事实不同则 ID 必须不同
        changed = observations()
        changed["pages"][0]["items"][0]["observedResponse"] = "71"
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest(), ensure_ascii=False), encoding="utf-8")
            other = retry.build_plan(manifest_path, changed)
        self.assertNotEqual(first_ids[0], other["events"][0]["eventId"])

    def test_maps_page_and_numbers_to_exact_manifest_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest(), ensure_ascii=False), encoding="utf-8")
            plan = retry.build_plan(manifest_path, observations())

        self.assertEqual(plan["eventCount"], 2)
        first, second = plan["events"]
        self.assertEqual(first["question_id"], "problem_one")
        self.assertIsNone(first["variant_id"])
        self.assertEqual(first["mastery"], "需再练")
        self.assertEqual(second["question_id"], "problem_two")
        self.assertEqual(second["variant_id"], "variant:v1:two:1")
        self.assertEqual(second["mastery"], "练习中")
        self.assertNotEqual(second["mastery"], "已掌握")

    def test_class_directory_resolves_private_instances_without_names_in_page_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for instance, name, number in (
                ("S001", "学生甲", "01"),
                ("S002", "学生乙", "02"),
            ):
                student_dir = root / "students" / instance
                student_dir.mkdir(parents=True)
                (student_dir / "manifest.json").write_text(
                    json.dumps(manifest(instance, name, number), ensure_ascii=False),
                    encoding="utf-8",
                )
            raw = observations()
            raw["pages"][0]["pageCode"] = "20260715-01-S002-P1"
            plan = retry.build_plan(root, raw)

        self.assertEqual(plan["events"][0]["instance_code"], "S002")
        self.assertEqual(plan["events"][0]["student_name"], "学生乙")
        self.assertEqual(plan["events"][0]["student_number"], "02")

    def test_invalid_page_code_and_duplicate_item_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(json.dumps(manifest(), ensure_ascii=False), encoding="utf-8")
            wrong = observations()
            wrong["pages"][0]["pageCode"] = "20260715-02-S001-P1"
            with self.assertRaisesRegex(retry.RetryBatchError, "pageCode"):
                retry.build_plan(path, wrong)

            duplicate = observations()
            duplicate["pages"][0]["items"].append(dict(duplicate["pages"][0]["items"][0]))
            with self.assertRaisesRegex(retry.RetryBatchError, "重复"):
                retry.build_plan(path, duplicate)

    def test_mastered_requires_explicit_teacher_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(json.dumps(manifest(), ensure_ascii=False), encoding="utf-8")
            raw = observations()
            raw["pages"][0]["items"][1]["teacherMastery"] = "已掌握"
            with self.assertRaisesRegex(retry.RetryBatchError, "教师判断"):
                retry.build_plan(path, raw)

            raw["pages"][0]["items"][1]["teacherJudgment"] = "连续两次独立完成。"
            plan = retry.build_plan(path, raw)

        self.assertEqual(plan["events"][1]["mastery"], "已掌握")

    def test_commit_is_idempotent_and_plan_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest(), ensure_ascii=False), encoding="utf-8")
            plan = retry.build_plan(path, observations())
            retry.validate_plan(plan)
            appended, duplicates = retry.append_events(plan, root / "events.jsonl")
            appended_again, duplicates_again = retry.append_events(plan, root / "events.jsonl")
            lines = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()

            tampered = json.loads(json.dumps(plan, ensure_ascii=False))
            tampered["events"][0]["question_id"] = "problem_changed"
            with self.assertRaisesRegex(retry.RetryBatchError, "稳定 ID"):
                retry.validate_plan(tampered)

            projection_tampered = json.loads(json.dumps(plan, ensure_ascii=False))
            projection_tampered["baseProjections"][0]["questionId"] = "problem_changed"
            with self.assertRaisesRegex(retry.RetryBatchError, "Base 投影"):
                retry.validate_plan(projection_tampered)

            count_tampered = json.loads(json.dumps(plan, ensure_ascii=False))
            count_tampered["needsHumanCount"] = 99
            with self.assertRaisesRegex(retry.RetryBatchError, "人工处理计数"):
                retry.validate_plan(count_tampered)

        self.assertEqual((appended, duplicates), (2, 0))
        self.assertEqual((appended_again, duplicates_again), (0, 2))
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
