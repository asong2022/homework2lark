from __future__ import annotations

from io import BytesIO
from threading import Event
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from tests.conftest import image_bytes

from mistake_notebook_api.api.runtime import Runtime
from mistake_notebook_api.domain.errors import OCRProviderError
from mistake_notebook_api.domain.ocr import OCRInput, OCRResult, ProviderHealth
from mistake_notebook_api.infrastructure.database.uow import SQLAlchemyUnitOfWork
from mistake_notebook_api.infrastructure.ocr.fake import FakeOCRProvider


@pytest.mark.parametrize(
    ("file_name", "image_format", "media_type"),
    [
        ("worksheet.png", "PNG", "image/png"),
        ("worksheet.jpg", "JPEG", "image/jpeg"),
        ("worksheet.jpeg", "JPEG", "image/jpeg"),
    ],
)
def test_upload_accepts_phase_one_image_formats(
    client: TestClient, file_name: str, image_format: str, media_type: str
) -> None:
    original = image_bytes(image_format)
    response = client.post(
        "/api/v1/assets",
        files={"file": (file_name, original, media_type)},
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["mediaType"] == media_type
    assert (asset["width"], asset["height"]) == (120, 80)
    assert client.get(asset["contentUrl"]).content == original


def test_duplicate_hash_is_reported_without_merging_assets(client: TestClient) -> None:
    original = image_bytes()
    first = client.post(
        "/api/v1/assets",
        files={"file": ("first.png", original, "image/png")},
    ).json()
    second = client.post(
        "/api/v1/assets",
        files={"file": ("second.png", original, "image/png")},
    ).json()

    assert second["assetId"] != first["assetId"]
    assert second["duplicateOfAssetId"] == first["assetId"]
    assert second["fileHash"] == first["fileHash"]
    assert client.get(second["contentUrl"]).content == original


def test_asset_problem_collection_restores_saved_regions_in_page_order(
    client: TestClient,
) -> None:
    upload = client.post(
        "/api/v1/assets",
        files={"file": ("worksheet.png", image_bytes(), "image/png")},
    ).json()
    lower = client.post(
        f"/api/v1/assets/{upload['assetId']}/regions",
        json={
            "coordinateSystem": "normalized_top_left",
            "bbox": {"x": 0.1, "y": 0.55, "width": 0.4, "height": 0.25},
        },
    ).json()
    upper = client.post(
        f"/api/v1/assets/{upload['assetId']}/regions",
        json={
            "coordinateSystem": "normalized_top_left",
            "bbox": {"x": 0.2, "y": 0.1, "width": 0.5, "height": 0.2},
        },
    ).json()

    response = client.get(f"/api/v1/assets/{upload['assetId']}/problems")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    collection = response.json()
    assert collection["assetId"] == upload["assetId"]
    assert collection["count"] == 2
    assert [item["problemId"] for item in collection["items"]] == [
        upper["problemId"],
        lower["problemId"],
    ]
    assert [item["region"]["regionId"] for item in collection["items"]] == [
        upper["regionId"],
        lower["regionId"],
    ]


def test_asset_problem_collection_distinguishes_empty_page_from_missing_asset(
    client: TestClient,
) -> None:
    upload = client.post(
        "/api/v1/assets",
        files={"file": ("worksheet.png", image_bytes(), "image/png")},
    ).json()

    empty = client.get(f"/api/v1/assets/{upload['assetId']}/problems")
    missing = client.get("/api/v1/assets/asset_missing/problems")

    assert empty.status_code == 200
    assert empty.json() == {"assetId": upload["assetId"], "count": 0, "items": []}
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "asset_not_found"


def _upload_and_region(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    upload = client.post(
        "/api/v1/assets",
        files={"file": ("worksheet.png", image_bytes(), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    asset = upload.json()
    region_response = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions",
        json={
            "coordinateSystem": "normalized_top_left",
            "bbox": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
        },
    )
    assert region_response.status_code == 201, region_response.text
    return asset, region_response.json()


def test_complete_review_flow_preserves_all_versions(client: TestClient) -> None:
    original = image_bytes()
    upload = client.post(
        "/api/v1/assets",
        files={"file": ("worksheet.png", original, "image/png")},
    )
    assert upload.status_code == 201
    asset = upload.json()
    assert client.get(asset["contentUrl"]).content == original

    region_response = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions",
        json={
            "coordinateSystem": "normalized_top_left",
            "bbox": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
        },
    )
    assert region_response.status_code == 201, region_response.text
    region = region_response.json()
    with Image.open(BytesIO(client.get(region["cropContentUrl"]).content)) as crop:
        assert crop.size == (60, 40)

    first_ocr_response = client.post(f"/api/v1/regions/{region['regionId']}/ocr-runs")
    assert first_ocr_response.status_code == 201, first_ocr_response.text
    first_ocr = first_ocr_response.json()
    assert first_ocr["rawResponse"]["engine"] == "fake"
    assert first_ocr["status"] == "succeeded"

    before_revision = client.get(f"/api/v1/problems/{region['problemId']}").json()
    assert before_revision["status"] == "needs_review"
    assert before_revision["futureReuseEligible"] is False
    assert before_revision["ocr"]["runId"] == first_ocr["runId"]
    assert len(before_revision["review"]["statusHistory"]) == 2

    missing_revision = client.post(
        f"/api/v1/problems/{region['problemId']}/review",
        json={"revisionId": "revision_missing"},
    )
    assert missing_revision.status_code == 409
    assert missing_revision.json()["error"]["code"] == "review_revision_required"

    corrected_text = "小明有24本书，平均放在6层书架上，每层放4本。"
    revision_response = client.post(
        f"/api/v1/regions/{region['regionId']}/revisions",
        json={
            "basedOnOcrRunId": first_ocr["runId"],
            "correctedText": corrected_text,
            "correctionNote": "补充答案",
        },
    )
    assert revision_response.status_code == 201, revision_response.text
    revision = revision_response.json()
    assert revision["revisionNumber"] == 1

    reviewed_response = client.post(
        f"/api/v1/problems/{region['problemId']}/review",
        json={"revisionId": revision["revisionId"]},
    )
    assert reviewed_response.status_code == 200, reviewed_response.text
    reviewed = reviewed_response.json()
    assert reviewed["status"] == "reviewed"
    assert reviewed["futureReuseEligible"] is True
    assert reviewed["humanRevision"]["correctedText"] == corrected_text
    assert reviewed["ocr"]["text"] == first_ocr["text"]
    assert reviewed["history"]["ocrRuns"][0]["rawResponse"] == first_ocr["rawResponse"]
    assert reviewed["lineage"] == {
        "sourceAssetId": asset["assetId"],
        "problemRegionId": region["regionId"],
        "detectionCandidateId": None,
        "detectionCandidateIds": [],
        "ocrRunId": first_ocr["runId"],
        "revisionId": revision["revisionId"],
    }
    assert reviewed["source"]["contentUrl"] == asset["contentUrl"]
    assert reviewed["region"]["cropContentUrl"] == region["cropContentUrl"]
    assert reviewed["review"]["statusHistory"][-1]["revisionId"] == revision["revisionId"]
    assert reviewed["source"]["fileHash"] == asset["fileHash"]
    assert client.get(asset["contentUrl"]).content == original

    event_count = len(reviewed["review"]["statusHistory"])
    idempotent = client.post(
        f"/api/v1/problems/{region['problemId']}/review",
        json={"revisionId": revision["revisionId"]},
    )
    assert idempotent.status_code == 200
    assert len(idempotent.json()["review"]["statusHistory"]) == event_count

    second_ocr_response = client.post(f"/api/v1/regions/{region['regionId']}/ocr-runs")
    assert second_ocr_response.status_code == 201
    second_ocr = second_ocr_response.json()
    after_retry = client.get(f"/api/v1/problems/{region['problemId']}").json()
    assert after_retry["status"] == "reviewed"
    assert after_retry["ocr"]["runId"] == first_ocr["runId"]
    assert after_retry["latestOcrRun"]["runId"] == second_ocr["runId"]
    assert len(after_retry["history"]["ocrRuns"]) == 2

    second_revision_response = client.post(
        f"/api/v1/regions/{region['regionId']}/revisions",
        json={
            "basedOnOcrRunId": second_ocr["runId"],
            "correctedText": f"{corrected_text}\n请写出思考过程。",
        },
    )
    assert second_revision_response.status_code == 201
    second_revision = second_revision_response.json()
    assert second_revision["revisionNumber"] == 2
    needs_review = client.get(f"/api/v1/problems/{region['problemId']}").json()
    assert needs_review["status"] == "needs_review"
    assert needs_review["review"]["reviewedAt"] is None
    assert needs_review["futureReuseEligible"] is False
    assert len(needs_review["history"]["revisions"]) == 2
    assert needs_review["history"]["revisions"][0]["correctedText"] == corrected_text


class FailingProvider:
    name = "failing"
    model_name = "failure-v1"

    def recognize(self, _: OCRInput) -> OCRResult:
        raise OCRProviderError("unavailable")

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(False, self.name, "unavailable")


class BlockingProvider:
    name = "blocking"
    model_name = "blocking-v1"

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def recognize(self, _: OCRInput) -> OCRResult:
        self.started.set()
        self.release.wait(timeout=5)
        return OCRResult(
            provider=self.name,
            model=self.model_name,
            provider_version="1.0",
            text="late result",
            confidence=1.0,
            blocks=[],
            raw_response={"late": True},
            warnings=[],
            processing_time_ms=5_000,
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, self.name, "ready")


def test_ocr_failure_is_persisted_and_retryable(client: TestClient, runtime: Runtime) -> None:
    asset, region = _upload_and_region(client)
    runtime.ocr_provider = FailingProvider()
    failure = client.post(f"/api/v1/regions/{region['regionId']}/ocr-runs")
    assert failure.status_code == 503
    body = failure.json()["error"]
    assert body["code"] == "ocr_provider_unavailable"
    assert body["retryable"] is True
    assert body["details"]["ocrRunId"].startswith("ocr_")
    assert client.get(asset["contentUrl"]).status_code == 200
    assert client.get(region["cropContentUrl"]).status_code == 200

    runtime.ocr_provider = FakeOCRProvider()
    retry = client.post(f"/api/v1/regions/{region['regionId']}/ocr-runs")
    assert retry.status_code == 201
    record = client.get(f"/api/v1/problems/{region['problemId']}").json()
    assert [run["status"] for run in record["history"]["ocrRuns"]] == [
        "failed",
        "succeeded",
    ]


def test_cross_region_ocr_and_revision_ids_are_rejected(client: TestClient) -> None:
    _, first_region = _upload_and_region(client)
    _, second_region = _upload_and_region(client)
    first_ocr = client.post(f"/api/v1/regions/{first_region['regionId']}/ocr-runs").json()

    cross_ocr_revision = client.post(
        f"/api/v1/regions/{second_region['regionId']}/revisions",
        json={
            "basedOnOcrRunId": first_ocr["runId"],
            "correctedText": "不允许跨题引用。",
        },
    )
    assert cross_ocr_revision.status_code == 422
    assert cross_ocr_revision.json()["error"]["code"] == "ocr_run_invalid"

    first_revision = client.post(
        f"/api/v1/regions/{first_region['regionId']}/revisions",
        json={
            "basedOnOcrRunId": first_ocr["runId"],
            "correctedText": "第一道题的教师修订。",
        },
    ).json()
    cross_problem_review = client.post(
        f"/api/v1/problems/{second_region['problemId']}/review",
        json={"revisionId": first_revision["revisionId"]},
    )
    assert cross_problem_review.status_code == 409
    assert cross_problem_review.json()["error"]["code"] == "review_revision_required"
    second_record = client.get(f"/api/v1/problems/{second_region['problemId']}").json()
    assert second_record["status"] == "draft"
    assert second_record["history"]["revisions"] == []


def test_upload_database_failure_compensates_only_new_source(
    client: TestClient, runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_commit(_: SQLAlchemyUnitOfWork) -> None:
        raise RuntimeError("forced database failure")

    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", fail_commit)
    response = client.post(
        "/api/v1/assets",
        files={"file": ("worksheet.png", image_bytes(), "image/png")},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert not [path for path in runtime.settings.storage_root.rglob("*") if path.is_file()]


def test_region_database_failure_keeps_source_and_compensates_crop(
    client: TestClient, runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = image_bytes()
    upload = client.post(
        "/api/v1/assets",
        files={"file": ("worksheet.png", original, "image/png")},
    ).json()

    def fail_commit(_: SQLAlchemyUnitOfWork) -> None:
        raise RuntimeError("forced database failure")

    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", fail_commit)
    response = client.post(
        f"/api/v1/assets/{upload['assetId']}/regions",
        json={
            "coordinateSystem": "normalized_top_left",
            "bbox": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
        },
    )

    assert response.status_code == 500
    assert client.get(upload["contentUrl"]).content == original
    crop_root = runtime.settings.storage_root / "crops"
    assert not crop_root.exists() or not [path for path in crop_root.rglob("*") if path.is_file()]


def test_ocr_deadline_persists_timeout_and_returns_promptly(
    client: TestClient, runtime: Runtime
) -> None:
    _, region = _upload_and_region(client)
    provider = BlockingProvider()
    runtime.ocr_provider = provider
    runtime.settings.ocr_timeout_seconds = 1

    started = perf_counter()
    failure = client.post(f"/api/v1/regions/{region['regionId']}/ocr-runs")
    elapsed = perf_counter() - started
    provider.release.set()

    assert provider.started.is_set()
    assert elapsed < 2
    assert failure.status_code == 504
    error = failure.json()["error"]
    assert error["code"] == "ocr_timeout"
    assert error["retryable"] is True

    record = client.get(f"/api/v1/problems/{region['problemId']}").json()
    timeout_run = record["history"]["ocrRuns"][-1]
    assert timeout_run["runId"] == error["details"]["ocrRunId"]
    assert timeout_run["status"] == "failed"
    assert timeout_run["errorCode"] == "timeout"


def test_invalid_upload_and_region_keep_stable_error_shape(client: TestClient) -> None:
    invalid = client.post(
        "/api/v1/assets",
        files={"file": ("fake.png", b"not an image", "image/png")},
    )
    assert invalid.status_code == 422
    assert set(invalid.json()["error"]) == {
        "code",
        "message",
        "details",
        "requestId",
        "retryable",
    }

    asset, _ = _upload_and_region(client)
    out_of_bounds = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions",
        json={
            "coordinateSystem": "normalized_top_left",
            "bbox": {"x": 0.9, "y": 0.1, "width": 0.2, "height": 0.5},
        },
    )
    assert out_of_bounds.status_code == 422
    assert out_of_bounds.json()["error"]["code"] == "invalid_region"


def test_framework_400_404_and_405_use_the_stable_error_envelope(client: TestClient) -> None:
    bad_request = client.post(
        "/api/v1/assets",
        content=b"not-a-valid-multipart-body",
        headers={"Content-Type": "multipart/form-data; boundary=broken"},
    )
    not_found = client.get("/api/v1/no-such-route")
    method_not_allowed = client.delete("/api/v1/health")

    assert bad_request.status_code == 400
    assert bad_request.json()["error"]["code"] == "bad_request"
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "route_not_found"
    assert not_found.json()["error"]["requestId"].startswith("req_")
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.json()["error"]["code"] == "method_not_allowed"
    assert method_not_allowed.json()["error"]["retryable"] is False
    assert "GET" in method_not_allowed.headers["allow"]


def test_denied_cors_preflight_still_has_request_correlation(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert response.headers["x-request-id"].startswith("req_")
    assert response.headers["content-type"].startswith("text/plain")
