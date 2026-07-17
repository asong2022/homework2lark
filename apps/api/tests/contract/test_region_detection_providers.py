from __future__ import annotations

import base64
import json

import pytest

from mistake_notebook_api.domain.detection import RegionDetectionInput
from mistake_notebook_api.domain.errors import JsonValue, RegionDetectionProviderError
from mistake_notebook_api.infrastructure.detection.manual import (
    ManualOnlyRegionDetectionProvider,
)
from mistake_notebook_api.infrastructure.yescan.client import (
    YescanApiClient,
    YescanClientError,
    create_signature,
)
from mistake_notebook_api.infrastructure.yescan.question_detection import (
    YescanQuestionDetectionProvider,
)


class FakeTransport:
    def __init__(self, response: JsonValue) -> None:
        self.response = response
        self.payload: dict[str, JsonValue] | None = None

    def post_json(
        self, *, url: str, payload: dict[str, JsonValue], timeout_seconds: int
    ) -> JsonValue:
        assert url == "https://scan-business.quark.cn/vision"
        assert timeout_seconds == 120
        self.payload = payload
        return self.response


class FailingTransport:
    def __init__(self, category: str) -> None:
        self.category = category

    def post_json(
        self, *, url: str, payload: dict[str, JsonValue], timeout_seconds: int
    ) -> JsonValue:
        raise YescanClientError(self.category)


def _response() -> dict[str, JsonValue]:
    return {
        "code": "00000",
        "message": None,
        "data": {
            "ImageInfo": [
                {
                    "Angle": 0,
                    "Width": 1600,
                    "Height": 2200,
                    "ImageBase64": base64.b64encode(b"returned-image").decode("ascii"),
                }
            ],
            "StructureInfo": [
                {
                    "Position": [[102, 223], [1489, 223], [1489, 522], [102, 522]],
                    "Detail": [
                        {"Type": "PrintedText", "Confidence": 1.0, "Value": "fixture"},
                        {"Type": "PrintedText", "Confidence": 0.8, "Value": "fixture"},
                    ],
                },
                {
                    "Position": [[120, 646], [1492, 646], [1492, 1093], [120, 1093]],
                    "Detail": [
                        {"Type": "PrintedText", "Confidence": 1.0, "Value": "fixture"},
                        {"Type": "Illustration", "Confidence": 1.4, "Value": "fixture"},
                    ],
                },
            ],
        },
    }


def _provider(response: JsonValue) -> tuple[YescanQuestionDetectionProvider, FakeTransport]:
    transport = FakeTransport(response)
    client = YescanApiClient(
        client_id="BACK_test",
        client_secret="test-secret",
        endpoint="https://scan-business.quark.cn/vision",
        timeout_seconds=120,
        transport=transport,
    )
    return YescanQuestionDetectionProvider(client), transport


def _input() -> RegionDetectionInput:
    return RegionDetectionInput(
        source_asset_id="asset_test",
        image_bytes=b"input-image-bytes",
        width=1600,
        height=2200,
    )


def test_manual_provider_never_fabricates_automatic_candidates() -> None:
    provider = ManualOnlyRegionDetectionProvider()

    with pytest.raises(RegionDetectionProviderError) as raised:
        provider.detect(_input())

    assert provider.name == "manual"
    assert raised.value.category == "configuration_error"
    health = provider.health_check()
    assert health.available is False
    assert health.provider == "manual"


def test_signature_matches_official_formula() -> None:
    signature = create_signature(
        client_id="BACK_test",
        client_secret="test-secret",
        sign_nonce="nonce",
        timestamp=1702467101020,
    )
    assert signature == "1673b34997d99aa991414df9bab962d60119c00f117d58959d0bb20b7da4174f"


def test_yescan_structure_groups_are_normalized_one_to_one_without_request_secrets() -> None:
    raw_response = _response()
    provider, transport = _provider(raw_response)

    result = provider.detect(_input())

    assert result.provider == "yescan"
    assert result.model == "RecognizeQuestion"
    assert result.raw_response == raw_response
    assert len(result.candidates) == 2
    assert result.candidates[0].bbox.x == 102
    assert result.candidates[0].bbox.width == 1387
    assert result.candidates[0].confidence == pytest.approx(0.9)
    assert result.candidates[1].metadata == {
        "detailCount": 2,
        "detailTypes": ["Illustration", "PrintedText"],
    }
    assert result.warnings == ["provider_confidence_out_of_range"]

    assert transport.payload is not None
    assert transport.payload["serviceOption"] == "structure"
    assert json.loads(str(transport.payload["inputConfigs"])) == {
        "function_option": "RecognizeQuestion"
    }
    assert json.loads(str(transport.payload["outputConfigs"])) == {"need_return_image": "True"}
    serialized_result = json.dumps(result.raw_response)
    assert "test-secret" not in serialized_result
    assert base64.b64encode(_input().image_bytes).decode("ascii") not in serialized_result


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("A0100", "configuration_error"),
        ("A0300", "unavailable"),
        ("A0401", "input_rejected"),
        ("UNKNOWN", "invalid_response"),
    ],
)
def test_vendor_errors_are_mapped_to_safe_categories(code: str, category: str) -> None:
    provider, _ = _provider({"code": code, "message": "sensitive vendor body", "data": None})

    with pytest.raises(RegionDetectionProviderError) as raised:
        provider.detect(_input())

    assert raised.value.category == category
    assert "sensitive" not in str(raised.value)


@pytest.mark.parametrize("category", ["timeout", "unavailable", "invalid_response"])
def test_transport_errors_are_mapped_without_details(category: str) -> None:
    client = YescanApiClient(
        client_id="BACK_test",
        client_secret="test-secret",
        endpoint="https://scan-business.quark.cn/vision",
        timeout_seconds=120,
        transport=FailingTransport(category),
    )
    provider = YescanQuestionDetectionProvider(client)

    with pytest.raises(RegionDetectionProviderError) as raised:
        provider.detect(_input())

    assert raised.value.category == category


@pytest.mark.parametrize(
    "mutate",
    [
        lambda response: response["data"]["ImageInfo"][0].update({"Angle": 90}),
        lambda response: response["data"]["ImageInfo"][0].update({"Width": 1599}),
        lambda response: response["data"]["StructureInfo"][0].update({"Position": None}),
        lambda response: response["data"]["StructureInfo"][0].update(
            {"Position": [[-1, 0], [10, 0], [10, 10], [-1, 10]]}
        ),
    ],
)
def test_unsafe_coordinate_responses_are_rejected(mutate: object) -> None:
    response = _response()
    assert callable(mutate)
    mutate(response)
    provider, _ = _provider(response)

    with pytest.raises(RegionDetectionProviderError) as raised:
        provider.detect(_input())

    assert raised.value.category == "invalid_response"


def test_empty_structures_are_successful_with_manual_fallback_warning() -> None:
    response = _response()
    data = response["data"]
    assert isinstance(data, dict)
    data["StructureInfo"] = []
    provider, _ = _provider(response)

    result = provider.detect(_input())

    assert result.candidates == []
    assert result.warnings == ["no_candidates"]


def test_health_check_does_not_make_a_network_request() -> None:
    provider, _ = _provider(_response())
    assert provider.health_check().available is True

    missing = YescanQuestionDetectionProvider(
        YescanApiClient(
            client_id="",
            client_secret="",
            endpoint="https://scan-business.quark.cn/vision",
            timeout_seconds=120,
        )
    )
    assert missing.health_check().message == "configuration_error"
