from __future__ import annotations

import json
from collections.abc import Callable

import pytest
import requests
from tests.conftest import image_bytes

from mistake_notebook_api.api.runtime import build_ocr_provider
from mistake_notebook_api.config import Settings
from mistake_notebook_api.domain.errors import JsonValue, OCRProviderError
from mistake_notebook_api.domain.ocr import OCRInput
from mistake_notebook_api.infrastructure.ocr.paddle_vl_api import (
    DEFAULT_MODEL,
    PaddleOCRVLAPIProvider,
    RequestsPaddleOCRVLApiTransport,
    parse_result_jsonl,
)


class FakeTransport:
    def __init__(
        self,
        *,
        statuses: list[dict[str, JsonValue]] | None = None,
        result_text: str | None = None,
    ) -> None:
        self.statuses = statuses or [
            {"data": {"state": "done", "resultUrl": {"jsonUrl": "https://result.test/a"}}}
        ]
        self.result_text = result_text or json.dumps(
            {
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": "计算：$24\\div6=4$"}},
                        {"markdown": {"text": "|数|答案|\n|-|-|\n|24|4|"}},
                    ]
                }
            },
            ensure_ascii=False,
        )
        self.submit_calls: list[dict[str, object]] = []
        self.status_calls: list[dict[str, object]] = []
        self.result_calls: list[dict[str, object]] = []

    def submit_job(
        self,
        *,
        url: str,
        token: str,
        image_bytes: bytes,
        media_type: str,
        model: str,
        optional_payload: dict[str, JsonValue],
        timeout_seconds: float,
    ) -> dict[str, JsonValue]:
        self.submit_calls.append(
            {
                "url": url,
                "token": token,
                "imageBytes": image_bytes,
                "mediaType": media_type,
                "model": model,
                "optionalPayload": optional_payload,
                "timeoutSeconds": timeout_seconds,
            }
        )
        return {"data": {"jobId": "job_1"}}

    def get_job(self, *, url: str, token: str, timeout_seconds: float) -> dict[str, JsonValue]:
        self.status_calls.append({"url": url, "token": token, "timeoutSeconds": timeout_seconds})
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]

    def get_result_jsonl(self, *, url: str, timeout_seconds: float) -> str:
        self.result_calls.append({"url": url, "timeoutSeconds": timeout_seconds})
        return self.result_text


class FakeResponse:
    def __init__(self, status_code: int, text: str, *, url: str = "https://result.test/a"):
        self.status_code = status_code
        self.text = text
        self.url = url


def ocr_input() -> OCRInput:
    return OCRInput(
        source_asset_id="asset_1",
        problem_region_id="region_1",
        image_bytes=image_bytes(),
        media_type="image/png",
    )


def provider(
    transport: FakeTransport,
    *,
    clock: Callable[[], float] = lambda: 0,
) -> PaddleOCRVLAPIProvider:
    return PaddleOCRVLAPIProvider(
        token="test-secret-token",
        transport=transport,
        poll_interval_seconds=1,
        poll_timeout_seconds=10,
        clock=clock,
        sleeper=lambda _: None,
    )


def test_hosted_provider_polls_and_normalizes_markdown_without_token_in_raw() -> None:
    transport = FakeTransport(
        statuses=[
            {"data": {"state": "pending"}},
            {"data": {"state": "running", "extractProgress": {"extractedPages": 0}}},
            {"data": {"state": "done", "resultUrl": {"jsonUrl": "https://result.test/a"}}},
        ]
    )

    result = provider(transport).recognize(ocr_input())

    assert result.provider == "paddleocr_vl_api"
    assert result.model == DEFAULT_MODEL
    assert result.provider_version == "official-api-v2"
    assert result.text == "计算：$24\\div6=4$\n\n|数|答案|\n|-|-|\n|24|4|"
    assert len(result.blocks) == 2
    assert result.blocks[0].metadata["format"] == "markdown"
    assert result.confidence is None
    assert "test-secret-token" not in str(result.raw_response)
    assert len(transport.status_calls) == 3
    assert transport.result_calls == [{"url": "https://result.test/a", "timeoutSeconds": 10}]
    submit = transport.submit_calls[0]
    assert submit["model"] == "PaddleOCR-VL-1.6"
    assert submit["imageBytes"] == ocr_input().image_bytes
    assert submit["optionalPayload"] == {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }


def test_empty_markdown_is_a_successful_empty_ocr_result() -> None:
    transport = FakeTransport(
        result_text='{"result":{"layoutParsingResults":[{"markdown":{"text":""}}]}}'
    )

    result = provider(transport).recognize(ocr_input())

    assert result.text == ""
    assert result.blocks == []
    assert result.warnings == ["ocr_empty_text"]


@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (401, "configuration_error"),
        (403, "configuration_error"),
        (408, "timeout"),
        (504, "timeout"),
        (429, "unavailable"),
        (500, "unavailable"),
        (400, "invalid_response"),
    ],
)
def test_requests_transport_maps_safe_http_errors(
    monkeypatch: pytest.MonkeyPatch, status_code: int, category: str
) -> None:
    def fake_post(*_: object, **__: object) -> FakeResponse:
        return FakeResponse(status_code, "private vendor body")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(OCRProviderError) as raised:
        RequestsPaddleOCRVLApiTransport().submit_job(
            url="https://provider.test/jobs",
            token="secret",
            image_bytes=b"image",
            media_type="image/png",
            model=DEFAULT_MODEL,
            optional_payload={},
            timeout_seconds=1,
        )

    assert raised.value.category == category
    assert "private vendor body" not in str(raised.value)


def test_requests_transport_submits_official_multipart_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(*args: object, **kwargs: object) -> FakeResponse:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeResponse(200, '{"data":{"jobId":"job_1"}}')

    monkeypatch.setattr(requests, "post", fake_post)

    result = RequestsPaddleOCRVLApiTransport().submit_job(
        url="https://provider.test/jobs",
        token="secret-token",
        image_bytes=b"image-bytes",
        media_type="image/png",
        model=DEFAULT_MODEL,
        optional_payload={
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        },
        timeout_seconds=30,
    )

    assert result == {"data": {"jobId": "job_1"}}
    assert captured["args"] == ("https://provider.test/jobs",)
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["headers"] == {"Authorization": "bearer secret-token"}
    assert kwargs["data"] == {
        "model": "PaddleOCR-VL-1.6",
        "optionalPayload": (
            '{"useDocOrientationClassify":false,'
            '"useDocUnwarping":false,"useChartRecognition":false}'
        ),
    }
    assert kwargs["files"] == {"file": ("problem-region.png", b"image-bytes", "image/png")}
    assert kwargs["timeout"] == 30


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (requests.Timeout("private timeout"), "timeout"),
        (requests.RequestException("private network"), "unavailable"),
    ],
)
def test_requests_transport_redacts_network_errors(
    monkeypatch: pytest.MonkeyPatch, exception: Exception, category: str
) -> None:
    def fake_post(*_: object, **__: object) -> FakeResponse:
        raise exception

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(OCRProviderError) as raised:
        RequestsPaddleOCRVLApiTransport().submit_job(
            url="https://provider.test/jobs",
            token="secret",
            image_bytes=b"image",
            media_type="image/png",
            model=DEFAULT_MODEL,
            optional_payload={},
            timeout_seconds=1,
        )

    assert raised.value.category == category
    assert "private" not in str(raised.value)


def test_result_download_never_sends_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_get(*args: object, **kwargs: object) -> FakeResponse:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeResponse(200, "result")

    monkeypatch.setattr(requests, "get", fake_get)

    result = RequestsPaddleOCRVLApiTransport().get_result_jsonl(
        url="https://result.test/a", timeout_seconds=1
    )

    assert result == "result"
    assert "headers" not in captured["kwargs"]


@pytest.mark.parametrize(
    ("statuses", "result_text", "category"),
    [
        ([{"data": {"state": "failed", "errorMsg": "private"}}], None, "unavailable"),
        ([{"data": {"state": "unknown"}}], None, "invalid_response"),
        (
            [
                {
                    "data": {
                        "state": "done",
                        "resultUrl": {"jsonUrl": "http://result.test/a"},
                    }
                }
            ],
            None,
            "invalid_response",
        ),
        (None, "not-json", "invalid_response"),
    ],
)
def test_provider_rejects_failed_or_malformed_results(
    statuses: list[dict[str, JsonValue]] | None,
    result_text: str | None,
    category: str,
) -> None:
    transport = FakeTransport(statuses=statuses, result_text=result_text)

    with pytest.raises(OCRProviderError) as raised:
        provider(transport).recognize(ocr_input())

    assert raised.value.category == category
    assert "private" not in str(raised.value)


def test_provider_enforces_total_poll_timeout() -> None:
    times = iter((0.0, 0.0, 0.0, 2.0))
    transport = FakeTransport(statuses=[{"data": {"state": "pending"}}])
    value = provider(transport, clock=lambda: next(times))
    value.poll_timeout_seconds = 1

    with pytest.raises(OCRProviderError) as raised:
        value.recognize(ocr_input())

    assert raised.value.category == "timeout"


def test_health_check_is_network_free_and_requires_https_and_token() -> None:
    transport = FakeTransport()
    assert provider(transport).health_check().available is True
    assert transport.submit_calls == []

    missing = PaddleOCRVLAPIProvider(token="", transport=transport)
    assert missing.health_check().message == "configuration_error"

    insecure = PaddleOCRVLAPIProvider(
        token="secret", job_url="http://provider.test/jobs", transport=transport
    )
    assert insecure.health_check().message == "configuration_error"


def test_runtime_builds_hosted_provider_from_secret_settings() -> None:
    settings = Settings(
        ocr_provider="paddleocr_vl_api",
        paddleocr_access_token="runtime-secret",
        ocr_timeout_seconds=120,
    )

    value = build_ocr_provider(settings)

    assert isinstance(value, PaddleOCRVLAPIProvider)
    assert value.model_name == "PaddleOCR-VL-1.6"
    assert value.poll_timeout_seconds == 115


def test_jsonl_parser_rejects_empty_or_nonstandard_json() -> None:
    for value in ("", '{"value":NaN}', '{"value":1e999}'):
        with pytest.raises(OCRProviderError) as raised:
            parse_result_jsonl(value)
        assert raised.value.category == "invalid_response"


def test_provider_repr_redacts_token() -> None:
    value = PaddleOCRVLAPIProvider(token="private-token")

    assert "private-token" not in repr(value)
