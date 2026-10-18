from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "intake_batch.py"
SPEC = importlib.util.spec_from_file_location("shi_homework2lark_intake_batch", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load intake_batch module")
intake_batch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = intake_batch
SPEC.loader.exec_module(intake_batch)


class FakeIntakeService:
    def __init__(self, *, fail_once: set[str] | None = None) -> None:
        self.fail_once = set(fail_once or ())
        self.calls: list[str] = []

    def start(self, path: Path, mode: str):
        self.calls.append(path.name)
        if path.name in self.fail_once:
            self.fail_once.remove(path.name)
            raise intake_batch.intake.SkillError(
                "api_unavailable",
                "simulated",
                retryable=True,
            )
        number = path.stem.removeprefix("q") or "1"
        return {
            "schemaVersion": intake_batch.intake.SESSION_VERSION,
            "mode": mode,
            "source": {
                "assetId": f"asset_{number}",
                "fileName": path.name,
                "mediaType": "image/png",
                "width": 600,
                "height": 900,
                "contentUrl": f"/api/v1/assets/asset_{number}/content",
            },
            "detection": (
                {
                    "runId": f"detection_{number}",
                    "provider": "yescan",
                    "model": "question-ocr",
                    "warnings": [],
                    "candidates": [
                        {
                            "candidateId": f"candidate_{number}",
                            "providerCandidateId": f"group_{number}",
                            "bbox": {"x": 1, "y": 2, "width": 3, "height": 4},
                            "normalizedBbox": {
                                "x": 0.1,
                                "y": 0.2,
                                "width": 0.3,
                                "height": 0.4,
                            },
                            "confidence": 0.9,
                            "readingOrder": 0,
                        }
                    ],
                }
                if mode == "chat"
                else None
            ),
            "problems": (
                [
                    {
                        "problemId": f"problem_{number}",
                        "regionId": f"region_{number}",
                        "cropContentUrl": f"/api/v1/regions/region_{number}/crop",
                        "bbox": {"x": 0, "y": 0, "width": 600, "height": 900},
                        "selectionSource": "manual",
                    }
                ]
                if mode == "single"
                else []
            ),
        }


class IntakeBatchTests(unittest.TestCase):
    def _input(self, root: Path, *, count: int = 3, mode: str = "single") -> Path:
        items = []
        for index in range(1, count + 1):
            image = root / f"q{index}.png"
            image.write_bytes(f"image-{index}".encode())
            items.append({"itemCode": f"I{index:02d}", "path": str(image.resolve())})
        path = root / "batch.json"
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": "intake-batch-v1",
                    "mode": mode,
                    "items": items,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_partial_failure_continues_and_retry_only_calls_failed_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self._input(root)
            state_path = root / "state.json"
            fake = FakeIntakeService(fail_once={"q2.png"})
            service = intake_batch.BatchIntakeService(fake)

            first = service.start(input_path, state_path)
            self.assertEqual(
                [item["outcome"] for item in first["items"]], ["created", "failed", "created"]
            )
            self.assertEqual(first["items"][0]["problemId"], "problem_1")
            self.assertNotIn("problemIds", first["items"][0])
            self.assertEqual(first["created"], 2)
            self.assertEqual(first["failed"], 1)
            self.assertEqual(fake.calls, ["q1.png", "q2.png", "q3.png"])

            second = service.start(input_path, state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(fake.calls, ["q1.png", "q2.png", "q3.png", "q2.png"])
        self.assertEqual(
            [item["outcome"] for item in second["items"]], ["no_change", "created", "no_change"]
        )
        self.assertEqual(second["noChange"], 2)
        self.assertTrue(all(item["status"] == "created" for item in state["items"]))

    def test_state_contains_only_minimal_non_private_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self._input(root, count=1)
            state_path = root / "state.json"

            intake_batch.BatchIntakeService(FakeIntakeService()).start(input_path, state_path)
            state_text = state_path.read_text(encoding="utf-8")
            state = json.loads(state_text)

        self.assertNotIn(str(root), state_text)
        self.assertNotIn("题干", state_text)
        self.assertNotIn("学生", state_text)
        self.assertNotIn("apiKey", state_text)
        self.assertEqual(
            set(state["items"][0]),
            {"itemCode", "fileName", "sha256", "size", "status", "problemIds", "sessionFile"},
        )

    def test_changed_input_and_damaged_state_stop_before_new_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self._input(root, count=1)
            state_path = root / "state.json"
            fake = FakeIntakeService()
            service = intake_batch.BatchIntakeService(fake)
            service.start(input_path, state_path)
            (root / "q1.png").write_bytes(b"replacement")

            with self.assertRaisesRegex(intake_batch.intake.SkillError, "输入已改变"):
                service.start(input_path, state_path)
            self.assertEqual(fake.calls, ["q1.png"])

            state_path.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(intake_batch.intake.SkillError, "损坏"):
                intake_batch.status(state_path)

    def test_same_name_and_content_in_a_different_path_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first_input = self._input(first_dir, count=1)
            state_path = root / "state.json"
            fake = FakeIntakeService()
            service = intake_batch.BatchIntakeService(fake)
            service.start(first_input, state_path)

            second_image = second_dir / "q1.png"
            second_image.write_bytes((first_dir / "q1.png").read_bytes())
            second_input = second_dir / "batch.json"
            second_input.write_text(
                json.dumps(
                    {
                        "schemaVersion": "intake-batch-v1",
                        "mode": "single",
                        "items": [{"itemCode": "I01", "path": str(second_image.resolve())}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(intake_batch.intake.SkillError, "输入已改变"):
                service.start(second_input, state_path)

        self.assertEqual(fake.calls, ["q1.png"])

    def test_chat_keeps_candidate_session_without_auto_selecting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self._input(root, count=1, mode="chat")
            state_path = root / "state.json"

            result = intake_batch.BatchIntakeService(FakeIntakeService()).start(
                input_path,
                state_path,
            )
            session_file = result["items"][0]["sessionFile"]
            session = json.loads((root / session_file).read_text(encoding="utf-8"))

        self.assertNotIn("problemId", result["items"][0])
        self.assertNotIn("problemIds", result["items"][0])
        self.assertTrue(session_file.startswith("sessions/"))
        self.assertTrue(session_file.endswith("/I01.json"))
        self.assertEqual(session["mode"], "chat")
        self.assertEqual(len(session["detection"]["candidates"]), 1)
        self.assertEqual(session["problems"], [])

    def test_session_write_failure_stops_before_following_items_and_persists_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self._input(root, count=2)
            state_path = root / "state.json"
            fake = FakeIntakeService()

            def writer(path, value):
                if "sessions" in path.parts:
                    raise PermissionError("simulated")
                intake_batch.atomic_write_json(path, value)

            service = intake_batch.BatchIntakeService(fake, writer=writer)
            with self.assertRaisesRegex(intake_batch.intake.SkillError, "会话文件"):
                service.start(input_path, state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            recovery_status = intake_batch.status(state_path)
            with self.assertRaisesRegex(intake_batch.intake.SkillError, "不能再次上传"):
                intake_batch.BatchIntakeService(fake).start(input_path, state_path)

        self.assertEqual(fake.calls, ["q1.png"])
        self.assertEqual(state["items"][0]["status"], "failed")
        self.assertEqual(state["items"][0]["error"]["code"], "session_write_failed")
        self.assertFalse(state["items"][0]["error"]["retryable"])
        self.assertEqual(recovery_status["items"][0]["problemId"], "problem_1")
        self.assertEqual(state["items"][1]["status"], "pending")

    def test_progress_state_write_failure_stops_the_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self._input(root, count=2)
            state_path = root / "state.json"
            fake = FakeIntakeService()
            state_writes = 0

            def writer(path, value):
                nonlocal state_writes
                if path == state_path.resolve():
                    state_writes += 1
                    if state_writes == 2:
                        raise PermissionError("simulated")
                intake_batch.atomic_write_json(path, value)

            with self.assertRaisesRegex(intake_batch.intake.SkillError, "进度"):
                intake_batch.BatchIntakeService(fake, writer=writer).start(input_path, state_path)

            self.assertEqual(fake.calls, ["q1.png"])
            resumed = intake_batch.BatchIntakeService(fake).start(input_path, state_path)

        self.assertEqual(fake.calls, ["q1.png", "q2.png"])
        self.assertEqual(resumed["items"][0]["outcome"], "no_change")
        self.assertEqual(resumed["created"], 2)

    def test_batches_in_the_same_directory_do_not_share_session_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self._input(root, count=1)
            service = intake_batch.BatchIntakeService(FakeIntakeService())
            first = service.start(input_path, root / "first-state.json")
            second = service.start(input_path, root / "second-state.json")

            self.assertNotEqual(first["items"][0]["sessionFile"], second["items"][0]["sessionFile"])
            self.assertEqual(intake_batch.status(root / "first-state.json")["created"], 1)
            self.assertEqual(intake_batch.status(root / "second-state.json")["created"], 1)

    def test_tampered_session_id_is_rejected_before_retrying(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self._input(root, count=1)
            state_path = root / "state.json"
            fake = FakeIntakeService()
            service = intake_batch.BatchIntakeService(fake)
            result = service.start(input_path, state_path)
            session_path = root / result["items"][0]["sessionFile"]
            session = json.loads(session_path.read_text(encoding="utf-8"))
            session["problems"][0]["problemId"] = "problem_other"
            session_path.write_text(json.dumps(session), encoding="utf-8")

            with self.assertRaisesRegex(intake_batch.intake.SkillError, "题目 ID 不一致"):
                service.start(input_path, state_path)

        self.assertEqual(fake.calls, ["q1.png"])

    def test_validates_item_codes_and_twenty_image_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = self._input(root, count=20)
            self.assertEqual(len(intake_batch.load_batch_input(valid).items), 20)

            raw = json.loads(valid.read_text(encoding="utf-8"))
            raw["items"][1]["itemCode"] = "I03"
            valid.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(intake_batch.intake.SkillError, "I01"):
                intake_batch.load_batch_input(valid)

            too_many = self._input(root, count=21)
            with self.assertRaisesRegex(intake_batch.intake.SkillError, "1～20"):
                intake_batch.load_batch_input(too_many)


if __name__ == "__main__":
    unittest.main()
