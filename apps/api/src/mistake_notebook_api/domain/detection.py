from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from mistake_notebook_api.domain.errors import JsonValue
from mistake_notebook_api.domain.geometry import BoundingBox


@dataclass(frozen=True, slots=True)
class RegionDetectionInput:
    source_asset_id: str
    image_bytes: bytes
    width: int
    height: int
    media_type: str = "image/png"


@dataclass(frozen=True, slots=True)
class RegionCandidate:
    provider_candidate_id: str
    bbox: BoundingBox
    confidence: float | None
    reading_order: int
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RegionDetectionResult:
    provider: str
    model: str | None
    provider_version: str | None
    candidates: list[RegionCandidate]
    raw_response: JsonValue
    warnings: list[str]
    processing_time_ms: int


@dataclass(frozen=True, slots=True)
class DetectionProviderHealth:
    available: bool
    provider: str
    message: str


class ProblemRegionDetectionProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model_name(self) -> str | None: ...

    def detect(self, input: RegionDetectionInput) -> RegionDetectionResult: ...

    def health_check(self) -> DetectionProviderHealth: ...
