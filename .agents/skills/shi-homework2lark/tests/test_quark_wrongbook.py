from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "quark_wrongbook.py"
SPEC = importlib.util.spec_from_file_location("homework_quark_wrongbook", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load quark wrongbook module")
wrongbook = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wrongbook
SPEC.loader.exec_module(wrongbook)

NOW = "2026-08-02T08:00:00+00:00"
PNG = b"\x89PNG\r\n\x1a\n" + (b"x" * 24)


class StubClient:
    def __init__(self, questions):
        self.questions = list(questions)
        self.list_calls = 0
        self.download_calls = []

    def list_questions(self):
        self.list_calls += 1
        return list(self.questions)

    def download_image(self, question):
        self.download_calls.append(question.question_id)
        return wrongbook.DownloadedImage(PNG, ".png")


class StubImporter:
    def __init__(self):
        self.calls = 0

    def import_image(self, image):
        self.calls += 1
        return f"problem_{self.calls}"


class StubResponse:
    def __init__(self, value):
        self.payload = json.dumps(value).encode("utf-8") if not isinstance(value, bytes) else value

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]


class SequenceOpener:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self, _request, *, timeout):
        del timeout
        if not self.values:
            raise AssertionError("unexpected request")
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return StubResponse(value)


def question(question_id: str, image_url: str | None = None):
    return wrongbook.RemoteQuestion(
        question_id, image_url or f"https://img.example/{question_id}.png"
    )


class WrongbookServiceTests(unittest.TestCase):
    def test_baseline_excludes_history_without_download_or_import(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old_1"), question("old_2")])
            importer = StubImporter()
            service = wrongbook.WrongbookService(
                store,
                client=client,
                importer=importer,
                now=lambda: NOW,
            )

            result = service.baseline()
            repeated = wrongbook.WrongbookService(store, now=lambda: NOW).baseline()
            state_text = store.path.read_text(encoding="utf-8")

        self.assertEqual(result["baselineExcludedCount"], 2)
        self.assertEqual(result["downloadedCount"], 0)
        self.assertEqual(result["problemCreatedCount"], 0)
        self.assertEqual(repeated["status"], "no_change")
        self.assertEqual(client.list_calls, 1)
        self.assertEqual(client.download_calls, [])
        self.assertEqual(importer.calls, 0)
        self.assertNotIn("https://", state_text)
        self.assertNotIn("题干", state_text)

    def test_sync_adds_only_new_ids_and_preserves_ignored_items(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()

            client.questions = [question("old"), question("new_1"), question("new_2")]
            first_sync = service.sync()
            service.ignore(["new_1"])
            second_sync = service.sync()
            status = service.status()

        self.assertEqual(first_sync["discoveredCount"], 2)
        self.assertEqual(second_sync["discoveredCount"], 0)
        self.assertEqual(status["baselineExcludedCount"], 1)
        self.assertEqual(status["pendingCount"], 1)
        self.assertEqual(status["ignoredCount"], 1)
        self.assertEqual(status["pending"][0]["questionId"], "new_2")

    def test_collect_new_imports_existing_pending_and_new_items_with_one_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()
            client.questions = [
                question("old"),
                question("pending_1"),
                question("ignored_1"),
                question("imported_1"),
            ]
            service.sync()
            service.ignore(["ignored_1"])
            wrongbook.WrongbookService(
                store,
                client=client,
                importer=StubImporter(),
                now=lambda: NOW,
            ).import_questions(["imported_1"])

            client.questions = [
                question("old"),
                question("pending_1"),
                question("ignored_1"),
                question("imported_1"),
                question("new_1"),
                question("new_2"),
            ]
            client.list_calls = 0
            client.download_calls = []
            importer = StubImporter()
            importer.calls = 100
            result = wrongbook.WrongbookService(
                store,
                client=client,
                importer=importer,
                now=lambda: NOW,
            ).collect_new()

        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["discoveredCount"], 2)
        self.assertEqual(
            [item["questionId"] for item in result["imported"]],
            ["pending_1", "new_1", "new_2"],
        )
        self.assertEqual(result["baselineExcludedCount"], 1)
        self.assertEqual(result["pendingCount"], 0)
        self.assertEqual(result["importedCount"], 4)
        self.assertEqual(result["ignoredCount"], 1)
        self.assertEqual(client.list_calls, 1)
        self.assertEqual(client.download_calls, ["pending_1", "new_1", "new_2"])
        self.assertEqual(importer.calls, 103)

    def test_collect_new_without_new_or_pending_items_is_a_download_free_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()
            client.list_calls = 0
            importer = StubImporter()

            result = wrongbook.WrongbookService(
                store,
                client=client,
                importer=importer,
                now=lambda: NOW,
            ).collect_new()

        self.assertEqual(result["status"], "no_change")
        self.assertEqual(result["discoveredCount"], 0)
        self.assertEqual(result["downloadedCount"], 0)
        self.assertEqual(result["problemCreatedCount"], 0)
        self.assertEqual(client.list_calls, 1)
        self.assertEqual(client.download_calls, [])
        self.assertEqual(importer.calls, 0)

    def test_collect_new_requires_existing_baseline_without_remote_access(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("current")])

            with self.assertRaises(wrongbook.WrongbookError) as captured:
                wrongbook.WrongbookService(
                    store,
                    client=client,
                    importer=StubImporter(),
                    now=lambda: NOW,
                ).collect_new()

        self.assertEqual(captured.exception.code, "baseline_required")
        self.assertEqual(client.list_calls, 0)
        self.assertEqual(client.download_calls, [])

    def test_collect_new_partial_failure_preserves_success_and_pending_remainder(self):
        class SecondImportFails(StubImporter):
            def import_image(self, image):
                if self.calls == 1:
                    raise wrongbook.WrongbookError("import_failed", "第二题失败。")
                return super().import_image(image)

        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()
            client.questions = [question("old"), question("new_1"), question("new_2")]

            with self.assertRaises(wrongbook.WrongbookError):
                wrongbook.WrongbookService(
                    store,
                    client=client,
                    importer=SecondImportFails(),
                    now=lambda: NOW,
                ).collect_new()
            status = service.status()

        self.assertEqual(status["baselineExcludedCount"], 1)
        self.assertEqual(status["importedCount"], 1)
        self.assertEqual(status["pendingCount"], 1)

    def test_collect_new_commits_available_items_before_a_missing_pending_item(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()
            client.questions = [
                question("old"),
                question("available_1"),
                question("missing_1"),
            ]
            service.sync()
            client.questions = [
                question("old"),
                question("available_1"),
                question("available_2"),
            ]

            with self.assertRaises(wrongbook.WrongbookError) as captured:
                wrongbook.WrongbookService(
                    store,
                    client=client,
                    importer=StubImporter(),
                    now=lambda: NOW,
                ).collect_new()
            status = service.status()

        self.assertEqual(captured.exception.code, "question_unavailable")
        self.assertEqual(captured.exception.details, {"questionId": "missing_1"})
        self.assertEqual(client.download_calls, ["available_1"])
        self.assertEqual(status["importedCount"], 1)
        self.assertEqual(status["pendingCount"], 2)

    def test_parser_exposes_collect_new_as_a_no_selection_command(self):
        parsed = wrongbook.build_parser().parse_args(["collect-new"])

        self.assertEqual(parsed.command, "collect-new")

    def test_import_selected_is_idempotent_and_leaves_unselected_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()
            client.questions = [question("old"), question("new_1"), question("new_2")]
            service.sync()
            importer = StubImporter()
            import_service = wrongbook.WrongbookService(
                store,
                client=client,
                importer=importer,
                now=lambda: NOW,
            )

            result = import_service.import_questions(["new_1"])
            repeated = wrongbook.WrongbookService(store, now=lambda: NOW).import_questions(
                ["new_1"]
            )
            status = import_service.status()

        self.assertEqual(result["imported"], [{"questionId": "new_1", "problemId": "problem_1"}])
        self.assertEqual(repeated["status"], "no_change")
        self.assertEqual(repeated["unchanged"][0]["problemId"], "problem_1")
        self.assertEqual(client.download_calls, ["new_1"])
        self.assertEqual(importer.calls, 1)
        self.assertEqual(status["pendingCount"], 1)
        self.assertEqual(status["importedCount"], 1)

    def test_import_all_pending_commits_each_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()
            client.questions = [question("old"), question("new_1"), question("new_2")]
            service.sync()
            importer = StubImporter()

            result = wrongbook.WrongbookService(
                store,
                client=client,
                importer=importer,
                now=lambda: NOW,
            ).import_questions(all_pending=True)

        self.assertEqual([item["questionId"] for item in result["imported"]], ["new_1", "new_2"])
        self.assertEqual(result["pendingCount"], 0)
        self.assertEqual(result["importedCount"], 2)

    def test_batch_failure_preserves_each_earlier_import(self):
        class SecondImportFails(StubImporter):
            def import_image(self, image):
                if self.calls == 1:
                    raise wrongbook.WrongbookError("import_failed", "第二题失败。")
                return super().import_image(image)

        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()
            client.questions = [question("old"), question("new_1"), question("new_2")]
            service.sync()
            importer = SecondImportFails()

            with self.assertRaises(wrongbook.WrongbookError):
                wrongbook.WrongbookService(
                    store,
                    client=client,
                    importer=importer,
                    now=lambda: NOW,
                ).import_questions(all_pending=True)
            status = service.status()

        self.assertEqual(status["importedCount"], 1)
        self.assertEqual(status["pendingCount"], 1)

    def test_state_failure_after_local_import_returns_recovery_problem_id(self):
        with tempfile.TemporaryDirectory() as directory:
            store = wrongbook.StateStore(Path(directory) / "state.json")
            client = StubClient([question("old")])
            service = wrongbook.WrongbookService(store, client=client, now=lambda: NOW)
            service.baseline()
            client.questions = [question("old"), question("new")]
            service.sync()
            importer = StubImporter()

            with (
                patch.object(
                    store,
                    "save",
                    side_effect=wrongbook.WrongbookError(
                        "state_write_failed",
                        "state failed",
                    ),
                ),
                self.assertRaises(wrongbook.WrongbookError) as captured,
            ):
                wrongbook.WrongbookService(
                    store,
                    client=client,
                    importer=importer,
                    now=lambda: NOW,
                ).import_questions(["new"])

            status = service.status()

        self.assertEqual(captured.exception.code, "state_write_failed")
        self.assertEqual(captured.exception.details["problemId"], "problem_1")
        self.assertEqual(status["pendingCount"], 1)

    def test_invalid_state_and_atomic_replace_failure_preserve_old_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = wrongbook.StateStore(path)
            wrongbook.WrongbookService(
                store,
                client=StubClient([question("old")]),
                now=lambda: NOW,
            ).baseline()
            before = path.read_bytes()
            state = store.load()
            state["updatedAt"] = "2026-08-02T09:00:00+00:00"

            with (
                patch.object(wrongbook.os, "replace", side_effect=OSError("blocked")),
                self.assertRaises(wrongbook.WrongbookError) as captured,
            ):
                store.save(state)

            leftovers = list(path.parent.glob(f".{path.name}.*.tmp"))
            after = path.read_bytes()

        self.assertEqual(captured.exception.code, "state_write_failed")
        self.assertEqual(after, before)
        self.assertEqual(leftovers, [])

    def test_single_importer_uses_existing_single_mode_and_removes_temp_file(self):
        class StubIntake:
            def __init__(self):
                self.path = None
                self.mode = None

            def start(self, path, mode):
                self.path = path
                self.mode = mode
                self.asserted_bytes = path.read_bytes()
                return {"problems": [{"problemId": "problem_existing"}]}

        intake = StubIntake()
        importer = wrongbook.SingleIntakeImporter("http://unused", service=intake)

        problem_id = importer.import_image(wrongbook.DownloadedImage(PNG, ".png"))

        self.assertEqual(problem_id, "problem_existing")
        self.assertEqual(intake.mode, "single")
        self.assertEqual(intake.asserted_bytes, PNG)
        self.assertFalse(intake.path.exists())


class QuarkHttpClientTests(unittest.TestCase):
    def test_repeated_pagination_stops_without_looping(self):
        page = [{"question_id": f"q{index}"} for index in range(wrongbook.PAGE_SIZE)]
        opener = SequenceOpener(
            [
                {"data": [{"course": "math", "total_question": 100}]},
                {"data": {"question_list": page}},
                {"data": {"question_list": page}},
            ]
        )
        client = wrongbook.QuarkHttpClient(
            ut="private-ut",
            kp="private-kp",
            opener=opener,
            sleep=lambda _seconds: None,
        )

        with self.assertRaises(wrongbook.WrongbookError) as captured:
            client.list_questions()

        self.assertEqual(captured.exception.code, "quark_pagination_repeated")

    def test_network_error_does_not_expose_credentials_or_authenticated_url(self):
        secret_ut = "private-ut-value"
        secret_kp = "private-kp-value"

        def failing_opener(request, *, timeout):
            del timeout
            raise urllib.error.URLError(request.full_url)

        client = wrongbook.QuarkHttpClient(
            ut=secret_ut,
            kp=secret_kp,
            opener=failing_opener,
        )

        with self.assertRaises(wrongbook.WrongbookError) as captured:
            client.list_questions()
        serialized = json.dumps(
            {
                "code": captured.exception.code,
                "message": captured.exception.message,
                "details": captured.exception.details,
            },
            ensure_ascii=False,
        )

        self.assertNotIn(secret_ut, serialized)
        self.assertNotIn(secret_kp, serialized)
        self.assertNotIn("?ut=", serialized)

    def test_missing_response_data_is_rejected(self):
        client = wrongbook.QuarkHttpClient(
            ut="private-ut",
            kp="private-kp",
            opener=SequenceOpener(
                [
                    {"data": [{"course": "math", "total_question": 1}]},
                    {},
                ]
            ),
        )

        with self.assertRaises(wrongbook.WrongbookError) as captured:
            client.list_questions()

        self.assertEqual(captured.exception.code, "quark_invalid_response")

    def test_invalid_download_image_is_rejected(self):
        opener = SequenceOpener([b"not-an-image"])
        client = wrongbook.QuarkHttpClient(
            ut="private-ut",
            kp="private-kp",
            opener=opener,
        )

        with self.assertRaises(wrongbook.WrongbookError) as captured:
            client.download_image(question("new"))

        self.assertEqual(captured.exception.code, "quark_image_invalid")

    def test_duplicate_question_with_conflicting_image_stops(self):
        first = question("same", "https://img.example/a.png")
        second = question("same", "https://img.example/b.png")

        with self.assertRaises(wrongbook.WrongbookError) as captured:
            wrongbook._merge_duplicate(first, second)

        self.assertEqual(captured.exception.code, "quark_duplicate_conflict")


if __name__ == "__main__":
    unittest.main()
