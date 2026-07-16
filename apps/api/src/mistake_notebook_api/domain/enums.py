from __future__ import annotations

from enum import StrEnum


class OCRRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RegionDetectionRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RegionSelectionSource(StrEnum):
    MANUAL = "manual"
    DETECTED = "detected"


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    OCR_COMPLETED = "ocr_completed"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"


class PublicationStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OCRBlockType(StrEnum):
    TEXT = "text"
    FORMULA = "formula"
    TABLE = "table"
    DIAGRAM = "diagram"
    UNKNOWN = "unknown"
