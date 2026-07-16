from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from mistake_notebook_api.domain.enums import OCRBlockType
from mistake_notebook_api.domain.errors import JsonValue
from mistake_notebook_api.domain.geometry import BoundingBox


@dataclass(frozen=True, slots=True)
class OCRBlock:
    type: OCRBlockType
    text: str
    bbox: BoundingBox | None
    confidence: float | None
    reading_order: int
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OCRInput:
    source_asset_id: str
    problem_region_id: str
    image_bytes: bytes
    media_type: str = "image/png"
    language: str = "ch"
    options: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OCRResult:
    provider: str
    model: str | None
    provider_version: str | None
    text: str
    confidence: float | None
    blocks: list[OCRBlock]
    raw_response: JsonValue
    warnings: list[str]
    processing_time_ms: int


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    available: bool
    provider: str
    message: str


class OCRProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model_name(self) -> str | None: ...

    def recognize(self, input: OCRInput) -> OCRResult: ...

    def health_check(self) -> ProviderHealth: ...
