from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "doctor.py"
SPEC = importlib.util.spec_from_file_location("homework_skill_doctor", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load doctor module")
doctor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = doctor
SPEC.loader.exec_module(doctor)


def _install_skill(root: Path, name: str) -> None:
    target = root / name
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")


class BundleManifestTests(unittest.TestCase):
    def test_skill_frontmatter_uses_only_standard_top_level_keys(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = skill.split("---", 2)[1]
        top_level_keys = {
            line.split(":", 1)[0]
            for line in frontmatter.splitlines()
            if line and not line[0].isspace()
        }

        self.assertLessEqual(
            top_level_keys,
            {"name", "description", "license", "allowed-tools", "metadata", "compatibility"},
        )
        self.assertNotIn("version", top_level_keys)
        self.assertIn('version: "2.3.0"', frontmatter)

    def test_bundle_declares_one_entry_and_five_stages(self) -> None:
        manifest = doctor.load_bundle(SKILL_ROOT)

        self.assertEqual(manifest["entrySkill"], "shi-homework2lark")
        self.assertEqual(
            [stage["id"] for stage in manifest["stages"]],
            ["intake", "mistakes", "variants", "practice", "feedback"],
        )
        for required_file in manifest["resources"]["requiredFiles"]:
            self.assertTrue((SKILL_ROOT / required_file).is_file(), required_file)

    def test_router_contains_all_handoffs_and_external_delegation(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        handoffs = (SKILL_ROOT / "references" / "orchestration-and-handoffs.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("唯一入口", skill)
        self.assertIn("禁止 AI 自动判断", skill)
        self.assertIn("lark-base", skill)
        self.assertIn("shi-ocr", skill)
        self.assertIn("wumu-jihe-html", skill)
        for block in (
            "task",
            "source",
            "questions",
            "mistakes",
            "base",
            "variants",
            "practice",
            "feedback",
        ):
            self.assertIn(f"[homework/{block}]", handoffs)
        self.assertTrue((SKILL_ROOT / "scripts" / "workflow.py").is_file())
        self.assertTrue((SKILL_ROOT / "scripts" / "retry_batch.py").is_file())


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = doctor.load_bundle(SKILL_ROOT)

    def test_ready_when_required_and_recommended_dependencies_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "lark-base",
                "shi-shared",
                "shi-ocr",
                "shi-mineru",
                "shi-paddleocr",
                "shi-kescan",
                "wumu-jihe-html",
            ):
                _install_skill(root, name)

            report = doctor.build_report(
                SKILL_ROOT,
                manifest=self.manifest,
                skill_roots=[root],
                command_available=lambda _name: True,
                module_available=lambda _name: True,
            )

        self.assertEqual(report["overallStatus"], "ready")
        self.assertTrue(all(stage["status"] == "ready" for stage in report["stages"]))
        self.assertEqual(report["privacy"]["networkCalls"], 0)

    def test_missing_recommended_ocr_degrades_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _install_skill(root, "lark-base")

            report = doctor.build_report(
                SKILL_ROOT,
                manifest=self.manifest,
                skill_roots=[root],
                command_available=lambda _name: True,
                module_available=lambda _name: True,
            )

        self.assertEqual(report["overallStatus"], "degraded")
        intake = next(stage for stage in report["stages"] if stage["id"] == "intake")
        self.assertEqual(intake["status"], "degraded")
        self.assertIn("skill:shi-ocr", intake["missingRecommended"])

    def test_missing_filesystem_base_degrades_because_cli_embedded_guide_remains(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = doctor.build_report(
                SKILL_ROOT,
                manifest=self.manifest,
                skill_roots=[Path(temp_dir)],
                command_available=lambda _name: True,
                module_available=lambda _name: True,
            )

        self.assertEqual(report["overallStatus"], "degraded")
        base_check = next(item for item in report["skills"] if item["name"] == "lark-base")
        self.assertFalse(base_check["available"])
        mistakes = next(stage for stage in report["stages"] if stage["id"] == "mistakes")
        self.assertIn("skill:lark-base", mistakes["missingRecommended"])

    def test_report_does_not_expose_discovered_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _install_skill(root, "lark-base")
            report = doctor.build_report(
                SKILL_ROOT,
                manifest=self.manifest,
                skill_roots=[root],
                command_available=lambda _name: True,
                module_available=lambda _name: True,
            )

            serialized = json.dumps(report, ensure_ascii=False)

        self.assertNotIn(str(root), serialized)
        self.assertNotIn(str(Path.home()), serialized)
        self.assertEqual(report["privacy"]["filesystemPathsReported"], 0)


if __name__ == "__main__":
    unittest.main()
