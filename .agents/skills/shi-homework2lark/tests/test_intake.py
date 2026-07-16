from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "intake.py"
SPEC = importlib.util.spec_from_file_location("shi_homework2lark_intake", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load intake module")
intake = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = intake
SPEC.loader.exec_module(intake)


class FakeGateway:
    def __init__(self, *, ocr_provider: str = "paddleocr", detection_provider: str = "yescan"):
        self.ocr_provider = ocr_provider
        self.detection_provider = detection_provider
        self.calls: list[tuple[str, object]] = []

    def health(self):
        self.calls.append(("health", None))
        return {
            "status": "ok",
            "database": "ok",
            "ocrProvider": self.ocr_provider,
            "regionDetectionProvider": self.detection_provider,
        }

    def upload(self, path: Path):
        self.calls.append(("upload", path.name))
        return {
            "assetId": "asset_1",
            "fileName": path.name,
            "mediaType": "image/png",
            "width": 600,
            "height": 900,
            "contentUrl": "/api/v1/assets/asset_1/content",
        }

    def detect(self, asset_id: str):
        self.calls.append(("detect", asset_id))
        return {
            "runId": "detection_1",
            "provider": self.detection_provider,
            "model": "yescan",
            "warnings": [],
            "candidates": [
                {
                    "detectionCandidateId": "candidate_1",
                    "providerCandidateId": "group_1",
                    "bbox": {"x": 10, "y": 20, "width": 500, "height": 200},
                    "normalizedBbox": {
                        "x": 1 / 60,
                        "y": 1 / 45,
                        "width": 5 / 6,
                        "height": 2 / 9,
                    },
                    "confidence": 0.98,
                    "readingOrder": 0,
                    "metadata": {"private": "not copied"},
                },
                {
                    "detectionCandidateId": "candidate_2",
                    "providerCandidateId": "group_2",
                    "bbox": {"x": 10, "y": 300, "width": 500, "height": 200},
                    "normalizedBbox": {
                        "x": 1 / 60,
                        "y": 1 / 3,
                        "width": 5 / 6,
                        "height": 2 / 9,
                    },
                    "confidence": 0.97,
                    "readingOrder": 1,
                    "metadata": {},
                },
            ],
        }

    def create_regions(self, asset_id: str, regions):
        self.calls.append(("create_regions", regions))
        return {
            "createdCount": len(regions),
            "items": [
                {
                    "problemId": f"problem_{index}",
                    "regionId": f"region_{index}",
                    "cropContentUrl": f"/api/v1/regions/region_{index}/crop",
                    "bbox": {"x": 10, "y": 20, "width": 500, "height": 200},
                    "selectionSource": region["selectionSource"],
                }
                for index, region in enumerate(regions, start=1)
            ],
        }

    def get_problem(self, problem_id: str):
        self.calls.append(("get_problem", problem_id))
        return {
            "problemId": problem_id,
            "status": "needs_review",
            "futureReuseEligible": False,
            "source": {
                "assetId": "asset_1",
                "fileName": "worksheet.png",
                "width": 600,
                "height": 900,
                "contentUrl": "/api/v1/assets/asset_1/content",
                "storageKey": "private/source.png",
                "fileHash": "private-hash",
            },
            "region": {
                "regionId": "region_1",
                "bbox": {"x": 10, "y": 20, "width": 500, "height": 200},
                "cropContentUrl": "/api/v1/regions/region_1/crop",
            },
            "latestOcrRun": {
                "runId": "ocr_1",
                "provider": self.ocr_provider,
                "model": "model",
                "status": "succeeded",
                "text": "24 支铅笔平均分给 6 人，每人多少支？",
                "confidence": 0.96,
                "warnings": [],
                "rawResponse": {"private": True},
            },
            "humanRevision": None,
            "review": {"status": "needs_review", "reviewedAt": None},
        }

    def run_ocr(self, region_id: str):
        self.calls.append(("run_ocr", region_id))
        return {
            "runId": "ocr_2",
            "provider": self.ocr_provider,
            "model": "model",
            "status": "succeeded",
            "text": "OCR 文本",
            "confidence": 0.95,
            "warnings": [],
        }

    def create_revision(self, region_id: str, payload):
        self.calls.append(("create_revision", payload))
        return {
            "revisionId": "revision_1",
            "revisionNumber": 1,
            "correctedText": payload["correctedText"],
            "correctionNote": payload["correctionNote"],
        }

    def review(self, problem_id: str, revision_id: str):
        self.calls.append(("review", revision_id))
        return {
            "problemId": problem_id,
            "status": "reviewed",
            "futureReuseEligible": True,
            "review": {"status": "reviewed", "reviewedAt": "2026-07-14T00:00:00+08:00"},
        }

    def publish(self, problem_id: str):
        self.calls.append(("publish", problem_id))
        return {
            "publisher": "lark_cli",
            "status": "succeeded",
            "baseName": "小学数学错题学习库",
            "retryable": False,
            "updatedAt": "2026-07-14T00:00:00+08:00",
            "questionRecordId": "private-record-id",
        }

    def download(self, path: str):
        self.calls.append(("download", path))
        return b"image"


class IntakeServiceTest(unittest.TestCase):
    def image(self, directory: str) -> Path:
        path = Path(directory) / "worksheet.png"
        path.write_bytes(b"png")
        return path

    def test_web_mode_uploads_once_without_detection_and_returns_manual_handoff(self):
        gateway = FakeGateway()
        service = intake.IntakeService(gateway, web_url="http://localhost:3000")
        with tempfile.TemporaryDirectory() as directory:
            manifest = service.start(self.image(directory), "web")

        self.assertEqual(manifest["mode"], "web")
        self.assertEqual(manifest["webUrl"], "http://localhost:3000/intake/asset_1")
        self.assertIsNone(manifest["detection"])
        self.assertNotIn("rawResponse", str(manifest))
        self.assertEqual([call[0] for call in gateway.calls], ["health", "upload"])

    def test_chat_mode_keeps_each_yescan_group_as_one_candidate_and_selects_explicit_ids(
        self,
    ):
        gateway = FakeGateway()
        service = intake.IntakeService(gateway)
        with tempfile.TemporaryDirectory() as directory:
            manifest = service.start(self.image(directory), "chat")
        detection = manifest["detection"]
        self.assertIsInstance(detection, dict)
        self.assertEqual(len(detection["candidates"]), 2)
        self.assertNotIn("metadata", detection["candidates"][0])

        selected = service.select(manifest, ["candidate_2"])

        self.assertEqual(selected["selectedCandidateIds"], ["candidate_2"])
        self.assertEqual(selected["problems"][0]["problemId"], "problem_1")
        create_call = next(call for call in gateway.calls if call[0] == "create_regions")
        self.assertEqual(create_call[1][0]["detectionCandidateIds"], ["candidate_2"])

    def test_single_mode_creates_one_full_image_problem(self):
        gateway = FakeGateway()
        service = intake.IntakeService(gateway)
        with tempfile.TemporaryDirectory() as directory:
            manifest = service.start(self.image(directory), "single")

        self.assertEqual(len(manifest["problems"]), 1)
        regions = next(call[1] for call in gateway.calls if call[0] == "create_regions")
        self.assertEqual(regions[0]["selectionSource"], "manual")
        self.assertEqual(regions[0]["bbox"], {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})

    def test_fake_providers_are_rejected_outside_explicit_test_mode(self):
        gateway = FakeGateway(detection_provider="fake", ocr_provider="fake")
        service = intake.IntakeService(gateway)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(intake.SkillError) as captured,
        ):
            service.start(self.image(directory), "web")
        self.assertEqual(captured.exception.code, "fake_provider_disabled")
        self.assertNotIn("upload", [call[0] for call in gateway.calls])

        gateway.calls.clear()
        with self.assertRaises(intake.SkillError) as captured:
            service.ocr("problem_1")
        self.assertEqual(captured.exception.code, "fake_provider_disabled")
        self.assertEqual([call[0] for call in gateway.calls], ["health"])

    def test_revision_review_and_publish_follow_the_review_gate(self):
        gateway = FakeGateway()
        service = intake.IntakeService(gateway)

        revision = service.save_revision(
            "problem_1",
            {"correctedText": "教师确认后的完整题目", "correctionNote": "修正单位"},
        )
        reviewed = service.review("problem_1", revision["revisionId"])
        published = service.publish("problem_1")

        self.assertEqual(revision["revisionId"], "revision_1")
        self.assertTrue(reviewed["futureReuseEligible"])
        self.assertEqual(published["status"], "succeeded")
        self.assertNotIn("questionRecordId", published)
        self.assertEqual(
            [call[0] for call in gateway.calls],
            ["get_problem", "create_revision", "review", "publish"],
        )

    def test_revision_strips_only_the_matching_outer_question_number(self):
        cases = (
            (
                "12. 学校把52本科普书平均分给4个班级。",
                "12",
                "学校把52本科普书平均分给4个班级。",
            ),
            ("15、下面4个点所表示的数是……", 15, "下面4个点所表示的数是……"),
            (
                "第 16 题：把一张正方形纸撕开后拼在一起。",
                "16",
                "把一张正方形纸撕开后拼在一起。",
            ),
        )
        for source, question_number, expected in cases:
            with self.subTest(source=source):
                gateway = FakeGateway()
                service = intake.IntakeService(gateway)

                result = service.save_revision(
                    "problem_1",
                    {"correctedText": source, "questionNumber": question_number},
                )

                self.assertEqual(result["correctedText"], expected)
                create_call = next(call for call in gateway.calls if call[0] == "create_revision")
                self.assertEqual(create_call[1]["correctedText"], expected)
                self.assertNotIn("questionNumber", create_call[1])

    def test_revision_keeps_content_number_without_a_matching_outer_number(self):
        cases = (
            (
                {"correctedText": "24支铅笔平均分给6人，每人多少支？"},
                "24支铅笔平均分给6人，每人多少支？",
            ),
            (
                {
                    "correctedText": "24支铅笔平均分给6人，每人多少支？",
                    "questionNumber": "12",
                },
                "24支铅笔平均分给6人，每人多少支？",
            ),
            (
                {"correctedText": "15. 实际题号不同。", "questionNumber": "12"},
                "15. 实际题号不同。",
            ),
        )
        for payload, expected in cases:
            with self.subTest(payload=payload):
                result = intake.IntakeService(FakeGateway()).save_revision("problem_1", payload)
                self.assertEqual(result["correctedText"], expected)

        with self.assertRaises(intake.SkillError) as captured:
            intake.IntakeService(FakeGateway()).save_revision(
                "problem_1", {"correctedText": "题干", "questionNumber": "0"}
            )
        self.assertEqual(captured.exception.code, "invalid_payload")

    def test_problem_projection_excludes_raw_provider_and_private_storage_fields(self):
        result = intake.IntakeService(FakeGateway()).get("problem_1")
        serialized = str(result)
        self.assertNotIn("rawResponse", serialized)
        self.assertNotIn("storageKey", serialized)
        self.assertNotIn("fileHash", serialized)
        self.assertEqual(result["ocr"]["text"], "24 支铅笔平均分给 6 人，每人多少支？")

    def test_pdf_requires_agent_level_page_normalization(self):
        service = intake.IntakeService(FakeGateway())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worksheet.pdf"
            path.write_bytes(b"pdf")
            with self.assertRaises(intake.SkillError) as captured:
                service.start(path, "web")
        self.assertEqual(captured.exception.code, "source_requires_page_images")

    def test_metadata_payload_allows_only_reviewable_catalog_fields(self):
        result = intake.validate_metadata_payload(
            {
                "problemId": "problem_1",
                "page": {
                    "页面名称": "三位数乘两位数练习",
                    "时间": "2026-07-14",
                    "年级": "四年级",
                    "课题名": "三位数乘两位数",
                    "错题来源": "作业本",
                },
                "question": {
                    "题目名称": "三位数乘两位数竖式问题",
                    "分区标题": "应用提升",
                    "题型": "计算题",
                    "对应知识点": "三位数乘两位数",
                },
                "note": "等待教师确认",
            }
        )
        self.assertEqual(result["page"]["课题名"], "三位数乘两位数")
        self.assertEqual(result["page"]["年级"], "四年级")
        self.assertEqual(result["question"]["分区标题"], "应用提升")
        self.assertEqual(result["question"]["题目名称"], "三位数乘两位数竖式问题")

        with self.assertRaises(intake.SkillError) as captured:
            intake.validate_metadata_payload(
                {"problemId": "problem_1", "question": {"页码": "116"}}
            )
        self.assertEqual(captured.exception.code, "invalid_payload")

        with self.assertRaises(intake.SkillError) as captured:
            intake.validate_metadata_payload({"problemId": "problem_1", "page": {"年级": "七年级"}})
        self.assertEqual(captured.exception.code, "invalid_payload")

        with self.assertRaises(intake.SkillError) as captured:
            intake.validate_metadata_payload(
                {"problemId": "problem_1", "question": {"审核状态": "已审核"}}
            )
        self.assertEqual(captured.exception.code, "invalid_payload")

        with self.assertRaises(intake.SkillError) as captured:
            intake.validate_metadata_payload(
                {"problemId": "problem_1", "question": {"题型": "自定义新分类"}}
            )
        self.assertEqual(captured.exception.code, "invalid_payload")

        with self.assertRaises(intake.SkillError) as captured:
            intake.validate_metadata_payload(
                {
                    "problemId": "problem_1",
                    "question": {"典型错例": "只计算了个位部分积。"},
                }
            )
        self.assertEqual(captured.exception.code, "invalid_payload")

    def test_json_input_accepts_absolute_path_outside_working_directory(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd().parent) as directory:
            source = Path(directory) / "selection.json"
            source.write_text('{"problemId":"problem_1"}', encoding="utf-8")

            loaded = intake._load_json(str(source.resolve()))

        self.assertEqual(loaded, {"problemId": "problem_1"})

    def test_http_gateway_resolves_api_content_urls_without_duplicate_prefix(self):
        gateway = intake.HttpGateway("http://127.0.0.1:8000/api/v1")

        self.assertEqual(
            gateway._url("/api/v1/assets/asset_1/content"),
            "http://127.0.0.1:8000/api/v1/assets/asset_1/content",
        )
        self.assertEqual(
            gateway._url("/assets/asset_1"),
            "http://127.0.0.1:8000/api/v1/assets/asset_1",
        )


if __name__ == "__main__":
    unittest.main()
