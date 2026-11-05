from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import image_bytes


def _region(client: TestClient) -> dict[str, str]:
    asset = client.post(
        "/api/v1/assets", files={"file": ("question.png", image_bytes(), "image/png")}
    ).json()
    return client.post(
        f"/api/v1/assets/{asset['assetId']}/regions",
        json={
            "coordinateSystem": "normalized_top_left",
            "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
        },
    ).json()


@pytest.mark.parametrize("source", ["ai_vision", "teacher"])
def test_image_revision_and_publication_work_without_ocr(client: TestClient, source: str) -> None:
    region = _region(client)
    response = client.post(
        f"/api/v1/regions/{region['regionId']}/revisions",
        json={"recognitionSource": source, "correctedText": "24支铅笔平均分给6人，每人多少支？"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["recognitionSource"] == source
    assert response.json()["basedOnOcrRunId"] is None

    published = client.post(f"/api/v1/problems/{region['problemId']}/publications/lark")
    assert published.status_code == 200, published.text
    record = client.get(f"/api/v1/problems/{region['problemId']}").json()
    assert record["ocr"] is None
    assert record["latestOcrRun"] is None
    assert record["history"]["ocrRuns"] == []
    assert record["humanRevision"]["recognitionSource"] == source
    assert client.get(record["region"]["cropContentUrl"]).status_code == 200


def test_vision_revision_does_not_claim_an_unrelated_historical_ocr_basis(
    client: TestClient,
) -> None:
    region = _region(client)
    run = client.post(f"/api/v1/regions/{region['regionId']}/ocr-runs").json()
    saved = client.post(
        f"/api/v1/regions/{region['regionId']}/revisions",
        json={"recognitionSource": "ai_vision", "correctedText": "从原图看清后的题干"},
    )
    assert saved.status_code == 201
    record = client.get(f"/api/v1/problems/{region['problemId']}").json()
    assert record["ocr"] is None
    assert record["latestOcrRun"]["runId"] == run["runId"]
    assert record["lineage"]["ocrRunId"] is None


def test_ocr_source_still_requires_a_valid_same_question_run(client: TestClient) -> None:
    first, second = _region(client), _region(client)
    run = client.post(f"/api/v1/regions/{first['regionId']}/ocr-runs").json()
    for payload in (
        {"correctedText": "缺少真实OCR依据"},
        {
            "recognitionSource": "ocr",
            "basedOnOcrRunId": run["runId"],
            "correctedText": "另一题的OCR",
        },
        {
            "recognitionSource": "teacher",
            "basedOnOcrRunId": run["runId"],
            "correctedText": "错误关联仍被拒绝",
        },
    ):
        response = client.post(f"/api/v1/regions/{second['regionId']}/revisions", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ocr_run_invalid"
