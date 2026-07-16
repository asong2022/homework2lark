from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from time import perf_counter

from mistake_notebook_api.domain.detection import (
    DetectionProviderHealth,
    RegionCandidate,
    RegionDetectionInput,
    RegionDetectionResult,
)
from mistake_notebook_api.domain.errors import (
    JsonValue,
    RegionDetectionProviderError,
)
from mistake_notebook_api.domain.geometry import BoundingBox
from mistake_notebook_api.infrastructure.yescan.client import (
    YescanApiClient,
    YescanClientError,
)

_CONFIGURATION_CODES = {"A0100", "A0202", "A0203", "A0205"}
_UNAVAILABLE_CODES = {"A0211", "A0300"}
_INPUT_REJECTED_PREFIX = "A04"


def _json_value(value: object) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise RegionDetectionProviderError("invalid_response")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise RegionDetectionProviderError("invalid_response")


def _number(value: JsonValue | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _polygon_bbox(value: JsonValue | None, *, source_width: int, source_height: int) -> BoundingBox:
    if not isinstance(value, list) or len(value) != 4:
        raise RegionDetectionProviderError("invalid_response")

    xs: list[float] = []
    ys: list[float] = []
    for point in value:
        if not isinstance(point, list) or len(point) < 2:
            raise RegionDetectionProviderError("invalid_response")
        x = _number(point[0])
        y = _number(point[1])
        if x is None or y is None:
            raise RegionDetectionProviderError("invalid_response")
        xs.append(x)
        ys.append(y)

    left = math.floor(min(xs))
    top = math.floor(min(ys))
    right = math.ceil(max(xs))
    bottom = math.ceil(max(ys))
    if (
        left < 0
        or top < 0
        or right > source_width
        or bottom > source_height
        or right <= left
        or bottom <= top
    ):
        raise RegionDetectionProviderError("invalid_response")
    return BoundingBox(left, top, right - left, bottom - top)


def _vendor_error_category(code: str) -> str:
    if code in _CONFIGURATION_CODES:
        return "configuration_error"
    if code in _UNAVAILABLE_CODES:
        return "unavailable"
    if code.startswith(_INPUT_REJECTED_PREFIX):
        return "input_rejected"
    return "invalid_response"


class YescanQuestionDetectionProvider:
    name = "yescan"
    model_name = "RecognizeQuestion"

    def __init__(self, client: YescanApiClient) -> None:
        self._client = client

    def detect(self, input: RegionDetectionInput) -> RegionDetectionResult:
        started = perf_counter()
        try:
            response = self._client.request(
                image_bytes=input.image_bytes,
                service_option="structure",
                function_option=self.model_name,
                output_configs={"need_return_image": "True"},
            )
        except YescanClientError as error:
            raise RegionDetectionProviderError(error.category) from None

        raw_response = _json_value(response)
        if not isinstance(raw_response, dict):
            raise RegionDetectionProviderError("invalid_response")
        code = raw_response.get("code")
        if code != "00000":
            category = _vendor_error_category(code) if isinstance(code, str) else "invalid_response"
            raise RegionDetectionProviderError(category)

        data = raw_response.get("data")
        if not isinstance(data, dict):
            raise RegionDetectionProviderError("invalid_response")
        image_info = data.get("ImageInfo")
        if not isinstance(image_info, list) or len(image_info) != 1:
            raise RegionDetectionProviderError("invalid_response")
        image = image_info[0]
        if not isinstance(image, dict):
            raise RegionDetectionProviderError("invalid_response")
        angle = _number(image.get("Angle"))
        width = _number(image.get("Width"))
        height = _number(image.get("Height"))
        returned_image = image.get("ImageBase64")
        if (
            angle is None
            or not math.isclose(angle, 0.0)
            or width != input.width
            or height != input.height
            or not isinstance(returned_image, str)
            or not returned_image
        ):
            raise RegionDetectionProviderError("invalid_response")

        structures = data.get("StructureInfo")
        if not isinstance(structures, list):
            raise RegionDetectionProviderError("invalid_response")

        warnings: list[str] = []
        candidates: list[RegionCandidate] = []
        for index, group in enumerate(structures):
            if not isinstance(group, dict):
                raise RegionDetectionProviderError("invalid_response")
            bbox = _polygon_bbox(
                group.get("Position"),
                source_width=input.width,
                source_height=input.height,
            )
            details_value = group.get("Detail", [])
            if not isinstance(details_value, list):
                raise RegionDetectionProviderError("invalid_response")

            confidences: list[float] = []
            detail_types: set[str] = set()
            for detail in details_value:
                if not isinstance(detail, dict):
                    raise RegionDetectionProviderError("invalid_response")
                detail_type = detail.get("Type")
                if isinstance(detail_type, str) and detail_type:
                    detail_types.add(detail_type)
                confidence = _number(detail.get("Confidence"))
                if confidence is not None:
                    if 0 <= confidence <= 1:
                        confidences.append(confidence)
                    elif "provider_confidence_out_of_range" not in warnings:
                        warnings.append("provider_confidence_out_of_range")

            detail_type_values: list[JsonValue] = []
            detail_type_values.extend(sorted(detail_types))
            metadata: dict[str, JsonValue] = {
                "detailCount": len(details_value),
                "detailTypes": detail_type_values,
            }
            candidates.append(
                RegionCandidate(
                    provider_candidate_id=str(index),
                    bbox=bbox,
                    confidence=(sum(confidences) / len(confidences) if confidences else None),
                    reading_order=index,
                    metadata=metadata,
                )
            )

        if not candidates:
            warnings.append("no_candidates")
        return RegionDetectionResult(
            provider=self.name,
            model=self.model_name,
            provider_version=None,
            candidates=candidates,
            raw_response=raw_response,
            warnings=warnings,
            processing_time_ms=max(1, round((perf_counter() - started) * 1000)),
        )

    def health_check(self) -> DetectionProviderHealth:
        if not self._client.is_configured:
            return DetectionProviderHealth(False, self.name, "configuration_error")
        return DetectionProviderHealth(True, self.name, "ready")
