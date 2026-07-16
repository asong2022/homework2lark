from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.conftest import image_bytes

from mistake_notebook_api.api.runtime import Runtime
from mistake_notebook_api.domain.detection import (
    DetectionProviderHealth,
    RegionDetectionInput,
    RegionDetectionResult,
)
from mistake_notebook_api.domain.errors import RegionDetectionProviderError
from mistake_notebook_api.infrastructure.database.uow import SQLAlchemyUnitOfWork


def _upload(client: TestClient, *, name: str = "worksheet.png") -> dict[str, object]:
    response = client.post(
        "/api/v1/assets",
        files={"file": (name, image_bytes(size=(600, 900)), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _detect(client: TestClient, asset_id: object) -> dict[str, object]:
    response = client.post(f"/api/v1/assets/{asset_id}/detection-runs")
    assert response.status_code == 201, response.text
    return response.json()


def _detected_selection(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "selectionSource": "detected",
        "detectionCandidateIds": [candidate["detectionCandidateId"]],
        "bbox": candidate["normalizedBbox"],
    }


def test_detection_persists_private_raw_evidence_and_returns_ordered_candidates(
    client: TestClient, runtime: Runtime
) -> None:
    asset = _upload(client)
    detection = _detect(client, asset["assetId"])

    assert detection["provider"] == "fake"
    assert detection["status"] == "succeeded"
    assert detection["errorCode"] is None
    assert [candidate["readingOrder"] for candidate in detection["candidates"]] == [0, 1, 2]
    assert [candidate["providerCandidateId"] for candidate in detection["candidates"]] == [
        "fake-1",
        "fake-2",
        "fake-3",
    ]
    assert "rawResponse" not in detection
    assert "rawResponseStorageKey" not in detection

    with runtime.uow_factory() as uow:
        persisted = uow.detections.get_run(str(detection["runId"]))
    assert persisted is not None
    assert persisted.raw_response_storage_key is not None
    evidence_path = runtime.settings.storage_root.joinpath(
        *persisted.raw_response_storage_key.split("/")
    )
    assert evidence_path.is_file()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence == {
        "engine": "fake",
        "candidateCount": 3,
        "sourceWidth": 600,
        "sourceHeight": 900,
    }


class FailingDetectionProvider:
    name = "failing-detection"
    model_name = "failure-v1"

    def __init__(self, category: str) -> None:
        self.category = category

    def detect(self, _: RegionDetectionInput) -> RegionDetectionResult:
        raise RegionDetectionProviderError(self.category)

    def health_check(self) -> DetectionProviderHealth:
        return DetectionProviderHealth(False, self.name, self.category)


def test_detection_failure_is_durable_and_manual_fallback_keeps_source(
    client: TestClient, runtime: Runtime
) -> None:
    asset = _upload(client)
    runtime.region_detection_provider = FailingDetectionProvider("timeout")

    response = client.post(f"/api/v1/assets/{asset['assetId']}/detection-runs")

    assert response.status_code == 504
    error = response.json()["error"]
    assert error["code"] == "region_detection_timeout"
    assert error["retryable"] is True
    assert client.get(asset["contentUrl"]).status_code == 200
    with runtime.uow_factory() as uow:
        persisted = uow.detections.get_run(error["details"]["detectionRunId"])
    assert persisted is not None
    assert persisted.status.value == "failed"
    assert persisted.error_code == "timeout"
    assert persisted.raw_response_storage_key is None

    manual = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions/batch",
        json={
            "coordinateSystem": "normalized_top_left",
            "regions": [
                {
                    "selectionSource": "manual",
                    "bbox": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.2},
                }
            ],
        },
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["items"][0]["selectionSource"] == "manual"


def test_batch_creates_only_confirmed_regions_with_selection_lineage(
    client: TestClient,
) -> None:
    asset = _upload(client)
    detection = _detect(client, asset["assetId"])
    candidates = detection["candidates"]
    assert isinstance(candidates, list)
    first = candidates[0]
    third = candidates[2]
    assert isinstance(first, dict)
    assert isinstance(third, dict)

    response = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions/batch",
        json={
            "coordinateSystem": "normalized_top_left",
            "regions": [
                _detected_selection(third),
                {
                    "selectionSource": "manual",
                    "bbox": {"x": 0.12, "y": 0.76, "width": 0.76, "height": 0.12},
                },
                _detected_selection(first),
            ],
        },
    )

    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["createdCount"] == 3
    assert [item["selectionSource"] for item in batch["items"]] == [
        "detected",
        "detected",
        "manual",
    ]
    assert batch["items"][0]["detectionCandidateId"] == first["detectionCandidateId"]
    assert batch["items"][1]["detectionCandidateId"] == third["detectionCandidateId"]
    assert batch["items"][2]["detectionCandidateId"] is None
    assert batch["items"][0]["detectionCandidateIds"] == [first["detectionCandidateId"]]
    assert batch["items"][1]["detectionCandidateIds"] == [third["detectionCandidateId"]]
    assert batch["items"][2]["detectionCandidateIds"] == []

    for item in batch["items"]:
        assert client.get(item["cropContentUrl"]).status_code == 200
        record = client.get(f"/api/v1/problems/{item['problemId']}")
        assert record.status_code == 200
        assert record.json()["region"]["selectionSource"] == item["selectionSource"]
        assert record.json()["status"] == "draft"


def test_multiple_detection_fragments_create_one_problem_with_complete_lineage(
    client: TestClient,
    runtime: Runtime,
) -> None:
    asset = _upload(client)
    detection = _detect(client, asset["assetId"])
    candidates = detection["candidates"]
    assert isinstance(candidates, list)
    first = candidates[0]
    second = candidates[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    first_bbox = first["normalizedBbox"]
    second_bbox = second["normalizedBbox"]
    assert isinstance(first_bbox, dict)
    assert isinstance(second_bbox, dict)
    left = min(float(first_bbox["x"]), float(second_bbox["x"]))
    top = min(float(first_bbox["y"]), float(second_bbox["y"]))
    right = max(
        float(first_bbox["x"]) + float(first_bbox["width"]),
        float(second_bbox["x"]) + float(second_bbox["width"]),
    )
    bottom = max(
        float(first_bbox["y"]) + float(first_bbox["height"]),
        float(second_bbox["y"]) + float(second_bbox["height"]),
    )
    candidate_ids = [first["detectionCandidateId"], second["detectionCandidateId"]]

    response = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions/batch",
        json={
            "coordinateSystem": "normalized_top_left",
            "regions": [
                {
                    "selectionSource": "detected",
                    "detectionCandidateIds": candidate_ids,
                    "bbox": {
                        "x": left,
                        "y": top,
                        "width": right - left,
                        "height": bottom - top,
                    },
                }
            ],
        },
    )

    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["createdCount"] == 1
    item = batch["items"][0]
    assert item["detectionCandidateId"] == candidate_ids[0]
    assert item["detectionCandidateIds"] == candidate_ids

    record_response = client.get(f"/api/v1/problems/{item['problemId']}")
    assert record_response.status_code == 200
    record = record_response.json()
    assert record["region"]["detectionCandidateIds"] == candidate_ids
    assert record["lineage"]["detectionCandidateIds"] == candidate_ids
    with runtime.engine.connect() as connection:
        source_rows = connection.execute(
            text(
                "SELECT detection_candidate_id, source_order "
                "FROM problem_region_candidate_sources "
                "WHERE problem_region_id = :region_id ORDER BY source_order"
            ),
            {"region_id": item["regionId"]},
        ).all()
    assert source_rows == [(candidate_ids[0], 0), (candidate_ids[1], 1)]

    reused = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions/batch",
        json={
            "coordinateSystem": "normalized_top_left",
            "regions": [_detected_selection(second)],
        },
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "region_candidate_already_used"


def test_batch_rejects_duplicate_cross_asset_and_reused_candidates(client: TestClient) -> None:
    first_asset = _upload(client, name="first.png")
    second_asset = _upload(client, name="second.png")
    detection = _detect(client, first_asset["assetId"])
    candidate = detection["candidates"][0]
    assert isinstance(candidate, dict)
    selection = _detected_selection(candidate)

    duplicate = client.post(
        f"/api/v1/assets/{first_asset['assetId']}/regions/batch",
        json={
            "coordinateSystem": "normalized_top_left",
            "regions": [selection, selection],
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "invalid_region_selection"

    cross_asset = client.post(
        f"/api/v1/assets/{second_asset['assetId']}/regions/batch",
        json={"coordinateSystem": "normalized_top_left", "regions": [selection]},
    )
    assert cross_asset.status_code == 422
    assert cross_asset.json()["error"]["code"] == "invalid_region_selection"

    created = client.post(
        f"/api/v1/assets/{first_asset['assetId']}/regions/batch",
        json={"coordinateSystem": "normalized_top_left", "regions": [selection]},
    )
    assert created.status_code == 201
    reused = client.post(
        f"/api/v1/assets/{first_asset['assetId']}/regions/batch",
        json={"coordinateSystem": "normalized_top_left", "regions": [selection]},
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "region_candidate_already_used"


def test_batch_database_failure_compensates_new_crops_only(
    client: TestClient,
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = _upload(client)
    detection = _detect(client, asset["assetId"])
    candidates = detection["candidates"]
    assert isinstance(candidates, list)
    selections = [_detected_selection(candidate) for candidate in candidates[:2]]
    evidence_files_before = set(
        (runtime.settings.storage_root / "provider-evidence").rglob("*.json")
    )

    def fail_commit(_: SQLAlchemyUnitOfWork) -> None:
        raise RuntimeError("forced database failure")

    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", fail_commit)
    response = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions/batch",
        json={"coordinateSystem": "normalized_top_left", "regions": selections},
    )

    assert response.status_code == 500
    crop_root = runtime.settings.storage_root / "crops"
    assert not crop_root.exists() or not [path for path in crop_root.rglob("*") if path.is_file()]
    assert set((runtime.settings.storage_root / "provider-evidence").rglob("*.json")) == (
        evidence_files_before
    )
    assert client.get(asset["contentUrl"]).status_code == 200


def test_detection_database_failure_compensates_new_evidence(
    client: TestClient,
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = _upload(client)

    def fail_commit(_: SQLAlchemyUnitOfWork) -> None:
        raise RuntimeError("forced database failure")

    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", fail_commit)
    response = client.post(f"/api/v1/assets/{asset['assetId']}/detection-runs")

    assert response.status_code == 500
    evidence_root = runtime.settings.storage_root / "provider-evidence"
    assert not evidence_root.exists() or not [
        path for path in evidence_root.rglob("*") if path.is_file()
    ]
    assert client.get(asset["contentUrl"]).status_code == 200


def test_batch_request_schema_rejects_empty_and_mismatched_lineage(client: TestClient) -> None:
    asset = _upload(client)
    empty = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions/batch",
        json={"coordinateSystem": "normalized_top_left", "regions": []},
    )
    mismatched = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions/batch",
        json={
            "coordinateSystem": "normalized_top_left",
            "regions": [
                {
                    "selectionSource": "manual",
                    "detectionCandidateIds": ["candidate_fake"],
                    "bbox": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.2},
                }
            ],
        },
    )

    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "validation_error"
    assert mismatched.status_code == 422
    assert mismatched.json()["error"]["code"] == "validation_error"
