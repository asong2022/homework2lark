from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mistake_notebook_api.domain.enums import (
    OCRRunStatus,
    PublicationStatus,
    RegionDetectionRunStatus,
    RegionSelectionSource,
)
from mistake_notebook_api.domain.errors import JsonValue


@dataclass(frozen=True, slots=True)
class SourceAsset:
    id: str
    file_name: str
    media_type: str
    storage_key: str
    file_hash: str
    width: int
    height: int
    file_size: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RegionDetectionRun:
    id: str
    source_asset_id: str
    provider: str
    provider_model: str | None
    provider_version: str | None
    status: RegionDetectionRunStatus
    error_code: str | None
    raw_response_storage_key: str | None
    warnings: list[str]
    started_at: datetime
    finished_at: datetime
    processing_time_ms: int


@dataclass(frozen=True, slots=True)
class RegionCandidate:
    id: str
    detection_run_id: str
    provider_candidate_id: str
    x: int
    y: int
    width: int
    height: int
    coordinate_system: str
    confidence: float | None
    reading_order: int
    metadata: dict[str, JsonValue]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProblemRegion:
    id: str
    source_asset_id: str
    page_number: int
    x: int
    y: int
    width: int
    height: int
    coordinate_system: str
    cropped_asset_key: str
    selection_source: RegionSelectionSource
    detection_candidate_id: str | None
    detection_candidate_ids: list[str]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OCRRun:
    id: str
    problem_region_id: str
    provider: str
    provider_model: str | None
    provider_version: str | None
    raw_response: JsonValue | None
    extracted_text: str | None
    confidence: float | None
    blocks: list[dict[str, JsonValue]]
    warnings: list[str]
    status: OCRRunStatus
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None
    processing_time_ms: int | None


@dataclass(frozen=True, slots=True)
class ProblemRevision:
    id: str
    problem_region_id: str
    based_on_ocr_run_id: str
    revision_number: int
    corrected_text: str
    correction_note: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProblemAsset:
    id: str
    problem_region_id: str
    current_revision_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProblemPublication:
    id: str
    problem_id: str
    source_asset_id: str
    publisher: str
    status: PublicationStatus
    published_revision_id: str
    base_name: str
    pages_table_id: str | None
    questions_table_id: str | None
    page_record_id: str | None
    question_record_id: str | None
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None
    updated_at: datetime
