from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
import runtime_service as runtime  # noqa: E402

STATE = {
    "migrations": "current",
    "runtimeId": "this-runtime",
    "capabilities": {
        "imageIntake": "ready",
        "pdf": "requires_agent_renderer",
        "word": "requires_agent_renderer",
    },
}
HEALTH = {"status": "ok", "database": "ok", "runtimeId": "this-runtime"}


class RuntimeServiceTests(unittest.TestCase):
    def test_check_rejects_pending_migration_without_starting_or_writing(self):
        with (
            patch.object(runtime, "_probe", return_value={**STATE, "migrations": "pending"}),
            patch.object(runtime.subprocess, "Popen") as spawn,
        ):
            with self.assertRaises(runtime.RuntimeServiceError) as captured:
                runtime.check(Path.cwd())
            self.assertEqual(captured.exception.code, "database_migration_pending")
            spawn.assert_not_called()

    def test_healthy_existing_runtime_is_reused_without_migration(self):
        with (
            patch.object(runtime, "_probe", return_value=STATE),
            patch.object(runtime, "_health", return_value=HEALTH),
            patch.object(runtime, "_command") as command,
            patch.object(runtime.subprocess, "Popen") as spawn,
        ):
            self.assertEqual(runtime.prepare(Path.cwd())["status"], "ready")
            command.assert_not_called()
            spawn.assert_not_called()

    def test_another_service_is_never_stopped_or_migrated(self):
        occupied = Mock()
        with (
            patch.object(runtime, "_probe", return_value=STATE),
            patch.object(runtime, "_health", return_value={**HEALTH, "runtimeId": "other"}),
            patch.object(runtime.socket, "create_connection", return_value=occupied),
            patch.object(runtime, "_command") as command,
            patch.object(runtime.subprocess, "Popen") as spawn,
        ):
            with self.assertRaises(runtime.RuntimeServiceError) as captured:
                runtime.prepare(Path.cwd())
            self.assertEqual(captured.exception.code, "runtime_port_in_use")
            command.assert_not_called()
            spawn.assert_not_called()
            occupied.close.assert_called_once()

    def test_prepare_migrates_then_starts_and_probes_only_its_own_runtime(self):
        process = Mock()
        process.poll.return_value = None
        with (
            patch.object(
                runtime, "_probe", side_effect=[{**STATE, "migrations": "pending"}, STATE, STATE]
            ),
            patch.object(runtime, "_health", side_effect=[None, HEALTH, HEALTH]),
            patch.object(runtime.socket, "create_connection", side_effect=OSError),
            patch.object(runtime, "_command", return_value=Mock(returncode=0)) as command,
            patch.object(runtime, "_python", return_value=Path(sys.executable)),
            patch.object(runtime.subprocess, "Popen", return_value=process) as spawn,
        ):
            self.assertEqual(runtime.prepare(Path.cwd())["status"], "ready")
            self.assertEqual(command.call_args.args[1], ["-m", "alembic", "upgrade", "head"])
            self.assertIn("127.0.0.1", spawn.call_args.args[0])
            process.terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
