from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclass(slots=True)
class OCRProviderError(Exception):
    category: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.category)


@dataclass(slots=True)
class RegionDetectionProviderError(Exception):
    category: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.category)


ERROR_STATUS_CODES: dict[str, int] = {
    "asset_too_large": 413,
    "unsupported_image": 415,
    "invalid_image": 422,
    "asset_not_found": 404,
    "region_not_found": 404,
    "problem_not_found": 404,
    "crop_not_found": 404,
    "invalid_region": 422,
    "invalid_region_selection": 422,
    "region_candidate_already_used": 409,
    "region_detection_input_rejected": 422,
    "region_detection_provider_configuration_error": 503,
    "region_detection_provider_unavailable": 503,
    "region_detection_timeout": 504,
    "region_detection_invalid_response": 502,
    "ocr_run_not_found": 404,
    "ocr_run_invalid": 422,
    "revision_not_found": 404,
    "revision_invalid": 422,
    "review_revision_required": 409,
    "problem_not_publishable": 409,
    "ocr_provider_configuration_error": 503,
    "ocr_provider_unavailable": 503,
    "ocr_timeout": 504,
    "ocr_invalid_response": 502,
    "lark_publisher_configuration_error": 503,
    "lark_publisher_unavailable": 503,
    "lark_publisher_invalid_response": 502,
    "storage_unavailable": 500,
    "route_not_found": 404,
    "method_not_allowed": 405,
    "bad_request": 400,
    "validation_error": 422,
    "internal_error": 500,
}
