from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "package_bundle.py"
if str(MODULE_PATH.parent) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("homework_package_bundle", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load package_bundle module")
package_bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = package_bundle
SPEC.loader.exec_module(package_bundle)


class PackageBundleTests(unittest.TestCase):
    def test_build_is_deterministic_and_has_one_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.skill"
            second = Path(temp_dir) / "second.skill"

            first_result = package_bundle.build_package(SKILL_ROOT, first)
            second_result = package_bundle.build_package(SKILL_ROOT, second)
            verification = package_bundle.verify_package(first)

            self.assertEqual(first_result["sha256"], second_result["sha256"])
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertTrue(verification["valid"])
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()

        self.assertTrue(all(name.startswith("shi-homework2lark/") for name in names))
        self.assertIn("shi-homework2lark/SKILL.md", names)
        self.assertIn("shi-homework2lark/bundle.json", names)
        self.assertFalse(any("__pycache__" in name for name in names))
        self.assertFalse(any(name.endswith(".pyc") for name in names))

    def test_collect_files_covers_manifest_resources(self) -> None:
        manifest = package_bundle.load_bundle(SKILL_ROOT)
        files = package_bundle.collect_files(SKILL_ROOT, manifest)

        for required in manifest["resources"]["requiredFiles"]:
            self.assertIn(Path(required), files)

    def test_private_path_and_credential_are_rejected_without_echoing_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bad_path = root / "bad.md"
            private_path = "C:" + "/Users/" + "Administrator/private"
            credential = "a" * 24
            bad_path.write_text(
                f"workspace = {private_path}\napi_key = '{credential}'\n",
                encoding="utf-8",
            )

            findings = package_bundle.scan_private_content(root, [Path("bad.md")])

        self.assertEqual(
            {item["reason"] for item in findings},
            {"private_absolute_path", "possible_credential"},
        )
        self.assertNotIn(credential, str(findings))

    def test_existing_output_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "bundle.skill"
            output.write_bytes(b"existing")

            with self.assertRaisesRegex(package_bundle.PackageError, "already exists"):
                package_bundle.build_package(SKILL_ROOT, output)


if __name__ == "__main__":
    unittest.main()
