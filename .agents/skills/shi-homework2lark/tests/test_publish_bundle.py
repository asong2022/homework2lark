from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "publish_bundle.py"
if str(MODULE_PATH.parent) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("homework_publish_bundle", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load publish_bundle module")
publish_bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publish_bundle
SPEC.loader.exec_module(publish_bundle)


class PublishBundleTests(unittest.TestCase):
    def test_sync_replaces_only_named_skill_and_verifies_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_root = Path(temp_dir) / "skills"
            target_root.mkdir()
            old = target_root / "shi-homework2lark"
            old.mkdir()
            (old / "obsolete.txt").write_text("old", encoding="utf-8")
            neighbor = target_root / "neighbor-skill"
            neighbor.mkdir()
            (neighbor / "keep.txt").write_text("keep", encoding="utf-8")

            result = publish_bundle.sync_to_root(SKILL_ROOT, target_root, kind="test")

            self.assertEqual(result["status"], "synced")
            self.assertTrue(result["hashesVerified"])
            self.assertFalse((old / "obsolete.txt").exists())
            self.assertTrue((old / "SKILL.md").is_file())
            self.assertEqual((neighbor / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertFalse(
                any(path.name.startswith(".shi-homework2lark.") for path in target_root.iterdir())
            )

    def test_dry_run_does_not_create_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_root = Path(temp_dir)

            result = publish_bundle.sync_to_root(SKILL_ROOT, target_root, kind="test", dry_run=True)

            self.assertEqual(result["status"], "would_sync")
            self.assertFalse((target_root / "shi-homework2lark").exists())

    def test_failed_post_publish_hash_check_restores_previous_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_root = Path(temp_dir) / "skills"
            target_root.mkdir()
            destination = target_root / "shi-homework2lark"
            destination.mkdir()
            (destination / "previous.txt").write_text("previous", encoding="utf-8")
            original_tree_hashes = publish_bundle.tree_hashes
            call_count = 0

            def fail_third_hash_check(root: Path, files: list[Path]) -> dict[str, str]:
                nonlocal call_count
                call_count += 1
                hashes = original_tree_hashes(root, files)
                if call_count == 3:
                    return {name: "invalid" for name in hashes}
                return hashes

            with (
                mock.patch.object(
                    publish_bundle,
                    "tree_hashes",
                    side_effect=fail_third_hash_check,
                ),
                self.assertRaisesRegex(
                    publish_bundle.PublishError,
                    "published mirror hash verification failed",
                ),
            ):
                publish_bundle.sync_to_root(SKILL_ROOT, target_root, kind="test")

            self.assertEqual(
                (destination / "previous.txt").read_text(encoding="utf-8"),
                "previous",
            )
            self.assertFalse(
                any(path.name.startswith(".shi-homework2lark.") for path in target_root.iterdir())
            )

    def test_family_repository_requires_known_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "skills").mkdir()

            with self.assertRaisesRegex(publish_bundle.PublishError, "README.md is missing"):
                publish_bundle.validate_family_root(repo)

            (repo / "README.md").write_text("family", encoding="utf-8")
            (repo / "scripts").mkdir()
            (repo / "scripts" / "sync-to-local.ps1").write_text("# sync", encoding="utf-8")
            self.assertEqual(publish_bundle.validate_family_root(repo), (repo / "skills").resolve())


if __name__ == "__main__":
    unittest.main()
