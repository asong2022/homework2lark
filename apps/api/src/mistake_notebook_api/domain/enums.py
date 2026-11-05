from __future__ import annotations

from enum import StrEnum


class RecognitionSource(StrEnum):
    OCR = "ocr"
    AI_VISION = "ai_vision"
    TEACHER = "teacher"


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
