from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from mistake_notebook_api.domain.entities import (
    OCRRun,
    ProblemPublication,
    ProblemRegion,
    ProblemRevision,
    RegionCandidate,
    RegionDetectionRun,
    ReviewedProblem,
    ReviewStatusEvent,
    SourceAsset,
)
from mistake_notebook_api.domain.enums import OCRRunStatus, ReviewStatus
from mistake_notebook_api.domain.errors import JsonValue


class SourceAssetRepository(Protocol):
    def add(self, asset: SourceAsset) -> None: ...

    def get(self, asset_id: str) -> SourceAsset | None: ...

    def find_first_by_hash(self, file_hash: str) -> SourceAsset | None: ...


class RegionDetectionRepository(Protocol):
    def add_run(self, run: RegionDetectionRun) -> None: ...

    def get_run(self, run_id: str) -> RegionDetectionRun | None: ...

    def add_candidate(self, candidate: RegionCandidate) -> None: ...

    def get_candidate(self, candidate_id: str) -> RegionCandidate | None: ...

    def list_candidates(self, run_id: str) -> list[RegionCandidate]: ...


class ProblemRepository(Protocol):
    def add_region(self, region: ProblemRegion) -> None: ...

    def get_region(self, region_id: str) -> ProblemRegion | None: ...

    def get_region_by_detection_candidate(self, candidate_id: str) -> ProblemRegion | None: ...

    def add_problem(self, problem: ReviewedProblem) -> None: ...

    def get_problem(self, problem_id: str) -> ReviewedProblem | None: ...

    def get_problem_by_region(self, region_id: str) -> ReviewedProblem | None: ...

    def list_problem_ids_by_asset(self, asset_id: str) -> list[str]: ...

    def update_problem(
        self,
        problem_id: str,
        *,
        current_revision_id: str | None,
        review_status: ReviewStatus,
        reviewed_at: datetime | None,
        updated_at: datetime,
    ) -> ReviewedProblem: ...

    def add_ocr_run(self, run: OCRRun) -> None: ...

    def get_ocr_run(self, run_id: str) -> OCRRun | None: ...

    def complete_ocr_run(
        self,
        run_id: str,
        *,
        status: OCRRunStatus,
        provider_model: str | None,
        provider_version: str | None,
        raw_response: JsonValue,
        extracted_text: str | None,
        confidence: float | None,
        blocks: list[dict[str, JsonValue]],
        warnings: list[str],
        error_code: str | None,
        finished_at: datetime,
        processing_time_ms: int,
    ) -> OCRRun: ...

    def list_ocr_runs(self, region_id: str) -> list[OCRRun]: ...

    def add_revision(self, revision: ProblemRevision) -> None: ...

    def get_revision(self, revision_id: str) -> ProblemRevision | None: ...

    def next_revision_number(self, region_id: str) -> int: ...

    def list_revisions(self, region_id: str) -> list[ProblemRevision]: ...

    def add_status_event(self, event: ReviewStatusEvent) -> None: ...

    def list_status_events(self, problem_id: str) -> list[ReviewStatusEvent]: ...


class ProblemPublicationRepository(Protocol):
    def add(self, publication: ProblemPublication) -> None: ...

    def get_by_problem(self, problem_id: str) -> ProblemPublication | None: ...

    def update(self, publication: ProblemPublication) -> None: ...


class UnitOfWork(Protocol):
    assets: SourceAssetRepository
    detections: RegionDetectionRepository
    problems: ProblemRepository
    publications: ProblemPublicationRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
