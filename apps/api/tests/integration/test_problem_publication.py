from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from fastapi.testclient import TestClient
from tests.conftest import image_bytes

from mistake_notebook_api.api.runtime import Runtime
from mistake_notebook_api.domain.publication import (
    ProblemPublicationRequest,
    ProblemPublicationResult,
    ProblemPublisherError,
)


def _create_problem(client: TestClient) -> dict[str, object]:
    asset = client.post(
        "/api/v1/assets",
        files={"file": ("worksheet.png", image_bytes(), "image/png")},
    ).json()
    region = client.post(
        f"/api/v1/assets/{asset['assetId']}/regions",
        json={
            "coordinateSystem": "normalized_top_left",
            "bbox": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
        },
    ).json()
    ocr = client.post(f"/api/v1/regions/{region['regionId']}/ocr-runs").json()
    return {"asset": asset, "region": region, "ocr": ocr}


def _save_revision(client: TestClient, context: dict[str, object]) -> dict[str, object]:
    region = context["region"]
    ocr = context["ocr"]
    assert isinstance(region, dict) and isinstance(ocr, dict)
    response = client.post(
        f"/api/v1/regions/{region['regionId']}/revisions",
        json={
            "basedOnOcrRunId": ocr["runId"],
            "correctedText": "24 支铅笔平均分给 6 名学生，每人分到多少支？",
        },
    )
    assert response.status_code == 201, response.text
    return client.get(f"/api/v1/problems/{region['problemId']}").json()


@dataclass
class RecordingPublisher:
    requests: list[ProblemPublicationRequest] = field(default_factory=list)
    failure: str | None = None

    @property
    def name(self) -> str:
        return "recording"

    def publish(self, request: ProblemPublicationRequest) -> ProblemPublicationResult:
        self.requests.append(request)
        if self.failure:
            raise ProblemPublisherError(self.failure)
        return ProblemPublicationResult(
            base_name="小学数学错题学习库",
            pages_table_id="tbl_pages",
            questions_table_id="tbl_questions",
            page_record_id=f"rec_page_{request.source_asset_id}",
            question_record_id=f"rec_question_{request.problem_id}",
        )


def test_problem_without_revision_cannot_be_published(client: TestClient) -> None:
    context = _create_problem(client)
    region = context["region"]
    assert isinstance(region, dict)

    response = client.post(f"/api/v1/problems/{region['problemId']}/publications/lark")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "problem_not_publishable"
    record = client.get(f"/api/v1/problems/{region['problemId']}").json()
    assert record["publication"] is None


def test_publish_is_retryable_and_keeps_one_local_state(
    client: TestClient, runtime: Runtime
) -> None:
    context = _create_problem(client)
    problem = _save_revision(client, context)
    publisher = RecordingPublisher()
    runtime.problem_publisher = publisher

    first = client.post(f"/api/v1/problems/{problem['problemId']}/publications/lark")
    second = client.post(f"/api/v1/problems/{problem['problemId']}/publications/lark")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["publicationId"] == second.json()["publicationId"]
    assert first.json()["questionRecordId"] == second.json()["questionRecordId"]
    assert len(publisher.requests) == 2
    assert publisher.requests[0].corrected_text == problem["humanRevision"]["correctedText"]
    assert publisher.requests[0].source_image_bytes == image_bytes()
    assert publisher.requests[0].source_file_hash == hashlib.sha256(image_bytes()).hexdigest()
    record = client.get(f"/api/v1/problems/{problem['problemId']}").json()
    assert record["humanRevision"] == problem["humanRevision"]
    assert record["publication"]["status"] == "succeeded"


def test_publisher_failure_is_persisted_without_changing_revision(
    client: TestClient, runtime: Runtime
) -> None:
    context = _create_problem(client)
    problem = _save_revision(client, context)
    runtime.problem_publisher = RecordingPublisher(failure="unavailable")

    response = client.post(f"/api/v1/problems/{problem['problemId']}/publications/lark")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "lark_publisher_unavailable"
    assert error["retryable"] is True
    record = client.get(f"/api/v1/problems/{problem['problemId']}").json()
    assert record["humanRevision"] == problem["humanRevision"]
    assert record["publication"]["status"] == "failed"
    assert record["publication"]["errorCode"] == "unavailable"
    assert record["publication"]["retryable"] is True
