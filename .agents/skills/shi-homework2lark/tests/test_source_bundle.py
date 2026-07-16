from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "source_bundle.py"
SPEC = importlib.util.spec_from_file_location("source_bundle", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load source_bundle")
source_bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = source_bundle
SPEC.loader.exec_module(source_bundle)


class SourceBundleTests(unittest.TestCase):
    def test_plan_routes_images_pdf_and_word_without_claiming_direct_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "image": root / "page.png",
                "pdf": root / "homework.pdf",
                "word": root / "homework.docx",
            }
            for path in files.values():
                path.write_bytes(b"test")
            image = source_bundle.plan_source(files["image"])
            pdf = source_bundle.plan_source(files["pdf"])
            word = source_bundle.plan_source(files["word"])
        self.assertTrue(image["directFastApiUpload"])
        self.assertFalse(pdf["directFastApiUpload"])
        self.assertEqual(pdf["route"], "mineru_plus_pdf_page_render")
        self.assertEqual(word["route"], "doc_render_plus_optional_mineru")

    def test_validate_requires_visual_pages_and_privacy_notice(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            image = root / "page-001.png"
            text = root / "page-001.md"
            image.write_bytes(b"page")
            text.write_text("# extracted", encoding="utf-8")
            raw = {
                "schemaVersion": 1,
                "sourceType": "pdf",
                "originalFileName": "作业.pdf",
                "privacyNoticeShown": True,
                "pages": [
                    {
                        "pageNumber": 1,
                        "pageImagePath": os.path.relpath(image, Path.cwd()),
                        "structuredTextPath": os.path.relpath(text, Path.cwd()),
                    }
                ],
            }
            result = source_bundle.validate_bundle(raw)
            raw["privacyNoticeShown"] = False
            with self.assertRaisesRegex(source_bundle.SourceError, "数据流向"):
                source_bundle.validate_bundle(raw)
        self.assertEqual(result["pageCount"], 1)
        self.assertEqual(result["next"], "send_each_page_to_chat_or_web_selection")

    def test_rejects_private_or_missing_manifest_fields(self):
        with self.assertRaises(source_bundle.SourceError):
            source_bundle.validate_bundle(
                {
                    "schemaVersion": 1,
                    "sourceType": "pdf",
                    "originalFileName": "作业.pdf",
                    "privacyNoticeShown": True,
                    "pages": [],
                    "apiKey": "must-not-appear",  # pragma: allowlist secret
                }
            )


if __name__ == "__main__":
    unittest.main()
