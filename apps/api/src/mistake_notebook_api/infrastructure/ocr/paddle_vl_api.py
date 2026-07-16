from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic, perf_counter, sleep
from typing import Protocol, cast
from urllib.parse import quote, urlparse

import requests

from mistake_notebook_api.domain.enums import OCRBlockType
from mistake_notebook_api.domain.errors import JsonValue, OCRProviderError
from mistake_notebook_api.domain.ocr import OCRBlock, OCRInput, OCRResult, ProviderHealth

PROVIDER_NAME = "paddleocr_vl_api"
PROVIDER_VERSION = "official-api-v2"
DEFAULT_MODEL = "PaddleOCR-VL-1.6"


def _reject_non_standard_json(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _json_value(value: object) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise OCRProviderError("invalid_response")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise OCRProviderError("invalid_response")
        return {str(key): _json_value(item) for key, item in value.items()}
    raise OCRProviderError("invalid_response")


def _parse_json(text: str) -> JsonValue:
    try:
        value = cast(
            object,
            json.loads(text, parse_constant=_reject_non_standard_json),
        )
    except (json.JSONDecodeError, ValueError):
        raise OCRProviderError("invalid_response") from None
    return _json_value(value)


def _require_dict(value: JsonValue | None) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise OCRProviderError("invalid_response")
    return value


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def parse_result_jsonl(value: str) -> list[dict[str, JsonValue]]:
    parsed: list[dict[str, JsonValue]] = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed.append(_require_dict(_parse_json(stripped)))
    if not parsed:
        raise OCRProviderError("invalid_response")
    return parsed


def normalize_paddleocr_vl_results(
    *,
    submission: dict[str, JsonValue],
    statuses: list[dict[str, JsonValue]],
    jsonl_results: list[dict[str, JsonValue]],
    model_name: str,
    processing_time_ms: int,
) -> OCRResult:
    blocks: list[OCRBlock] = []
    text_parts: list[str] = []

    for line_index, line in enumerate(jsonl_results):
        result = _require_dict(line.get("result"))
        layout_results = result.get("layoutParsingResults")
        if not isinstance(layout_results, list):
            raise OCRProviderError("invalid_response")
        for layout_index, layout_value in enumerate(layout_results):
            layout = _require_dict(layout_value)
            markdown_value = layout.get("markdown")
            if isinstance(markdown_value, dict):
                markdown_text = markdown_value.get("text")
            else:
                markdown_text = layout.get("markdownText")
            if not isinstance(markdown_text, str):
                raise OCRProviderError("invalid_response")
            normalized_text = markdown_text.strip()
            if not normalized_text:
                continue
            text_parts.append(normalized_text)
            blocks.append(
                OCRBlock(
                    type=OCRBlockType.TEXT,
                    text=normalized_text,
                    bbox=None,
                    confidence=None,
                    reading_order=len(blocks),
                    metadata={
                        "jsonlLine": line_index + 1,
                        "layoutIndex": layout_index,
                        "format": "markdown",
                    },
                )
            )

    text = "\n\n".join(text_parts)
    raw_response: dict[str, JsonValue] = {
        "submission": submission,
        "statuses": [status for status in statuses],
        "jsonl": [line for line in jsonl_results],
    }
    return OCRResult(
        provider=PROVIDER_NAME,
        model=model_name,
        provider_version=PROVIDER_VERSION,
        text=text,
        confidence=None,
        blocks=blocks,
        raw_response=raw_response,
        warnings=[] if text else ["ocr_empty_text"],
        processing_time_ms=processing_time_ms,
    )


class PaddleOCRVLApiTransport(Protocol):
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
    ) -> dict[str, JsonValue]: ...

    def get_job(self, *, url: str, token: str, timeout_seconds: float) -> dict[str, JsonValue]: ...

    def get_result_jsonl(self, *, url: str, timeout_seconds: float) -> str: ...


def _response_error(status_code: int) -> str | None:
    if 200 <= status_code < 300:
        return None
    if status_code in {401, 403}:
        return "configuration_error"
    if status_code in {408, 504}:
        return "timeout"
    if status_code == 429 or status_code >= 500:
        return "unavailable"
    return "invalid_response"


@dataclass(slots=True)
class RequestsPaddleOCRVLApiTransport:
    def _json_response(self, response: requests.Response) -> dict[str, JsonValue]:
        category = _response_error(response.status_code)
        if category is not None:
            raise OCRProviderError(category)
        return _require_dict(_parse_json(response.text))

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
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"bearer {token}"},
                data={
                    "model": model,
                    "optionalPayload": json.dumps(
                        optional_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                },
                files={"file": ("problem-region.png", image_bytes, media_type)},
                timeout=timeout_seconds,
            )
        except requests.Timeout:
            raise OCRProviderError("timeout") from None
        except requests.RequestException:
            raise OCRProviderError("unavailable") from None
        return self._json_response(response)

    def get_job(self, *, url: str, token: str, timeout_seconds: float) -> dict[str, JsonValue]:
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"bearer {token}"},
                timeout=timeout_seconds,
            )
        except requests.Timeout:
            raise OCRProviderError("timeout") from None
        except requests.RequestException:
            raise OCRProviderError("unavailable") from None
        return self._json_response(response)

    def get_result_jsonl(self, *, url: str, timeout_seconds: float) -> str:
        try:
            response = requests.get(url, timeout=timeout_seconds)
        except requests.Timeout:
            raise OCRProviderError("timeout") from None
        except requests.RequestException:
            raise OCRProviderError("unavailable") from None
        category = _response_error(response.status_code)
        if category is not None:
            raise OCRProviderError(category)
        if not _is_https_url(response.url):
            raise OCRProviderError("invalid_response")
        return response.text


@dataclass(slots=True)
class PaddleOCRVLAPIProvider:
    token: str = field(repr=False)
    job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    model: str = DEFAULT_MODEL
    request_timeout_seconds: float = 30
    poll_interval_seconds: float = 5
    poll_timeout_seconds: float = 115
    transport: PaddleOCRVLApiTransport = field(default_factory=RequestsPaddleOCRVLApiTransport)
    clock: Callable[[], float] = monotonic
    sleeper: Callable[[float], None] = sleep

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def is_configured(self) -> bool:
        return bool(
            self.token
            and _is_https_url(self.job_url)
            and self.model
            and self.request_timeout_seconds > 0
            and self.poll_interval_seconds > 0
            and self.poll_timeout_seconds > 0
        )

    def _request_timeout(self, deadline: float) -> float:
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise OCRProviderError("timeout")
        return min(self.request_timeout_seconds, remaining)

    def recognize(self, input: OCRInput) -> OCRResult:
        if not self.is_configured:
            raise OCRProviderError("configuration_error")

        started = perf_counter()
        deadline = self.clock() + self.poll_timeout_seconds
        optional_payload: dict[str, JsonValue] = {
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }
        submission = self.transport.submit_job(
            url=self.job_url,
            token=self.token,
            image_bytes=input.image_bytes,
            media_type=input.media_type,
            model=self.model,
            optional_payload=optional_payload,
            timeout_seconds=self._request_timeout(deadline),
        )
        submission_data = _require_dict(submission.get("data"))
        job_id = submission_data.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise OCRProviderError("invalid_response")

        statuses: list[dict[str, JsonValue]] = []
        result_url: str | None = None
        status_url = f"{self.job_url.rstrip('/')}/{quote(job_id, safe='')}"
        while result_url is None:
            status = self.transport.get_job(
                url=status_url,
                token=self.token,
                timeout_seconds=self._request_timeout(deadline),
            )
            statuses.append(status)
            status_data = _require_dict(status.get("data"))
            state = status_data.get("state")
            if state in {"pending", "running"}:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise OCRProviderError("timeout")
                self.sleeper(min(self.poll_interval_seconds, remaining))
                continue
            if state == "failed":
                raise OCRProviderError("unavailable")
            if state != "done":
                raise OCRProviderError("invalid_response")
            result_urls = _require_dict(status_data.get("resultUrl"))
            json_url = result_urls.get("jsonUrl")
            if not isinstance(json_url, str) or not _is_https_url(json_url):
                raise OCRProviderError("invalid_response")
            result_url = json_url

        jsonl_text = self.transport.get_result_jsonl(
            url=result_url,
            timeout_seconds=self._request_timeout(deadline),
        )
        jsonl_results = parse_result_jsonl(jsonl_text)
        return normalize_paddleocr_vl_results(
            submission=submission,
            statuses=statuses,
            jsonl_results=jsonl_results,
            model_name=self.model,
            processing_time_ms=max(1, round((perf_counter() - started) * 1000)),
        )

    def health_check(self) -> ProviderHealth:
        if not self.is_configured:
            return ProviderHealth(False, self.name, "configuration_error")
        return ProviderHealth(True, self.name, "ready")
