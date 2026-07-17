from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProblemPublicationRequest:
    source_asset_id: str
    source_file_hash: str
    source_file_name: str
    source_media_type: str
    source_image_bytes: bytes
    problem_id: str
    problem_region_id: str
    page_number: int
    crop_image_bytes: bytes
    revision_id: str
    revision_number: int
    corrected_text: str
    revision_created_at: datetime
    ocr_provider: str


@dataclass(frozen=True, slots=True)
class ProblemPublicationResult:
    base_name: str
    pages_table_id: str
    questions_table_id: str
    page_record_id: str
    question_record_id: str


@dataclass(slots=True)
class ProblemPublisherError(Exception):
    category: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.category)


class ProblemPublisher(Protocol):
    @property
    def name(self) -> str: ...

    def publish(self, request: ProblemPublicationRequest) -> ProblemPublicationResult: ...
