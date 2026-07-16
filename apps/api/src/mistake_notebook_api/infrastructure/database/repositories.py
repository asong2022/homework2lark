from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
from mistake_notebook_api.domain.enums import (
    OCRRunStatus,
    PublicationStatus,
    RegionDetectionRunStatus,
    RegionSelectionSource,
    ReviewStatus,
)
from mistake_notebook_api.domain.errors import JsonValue
from mistake_notebook_api.domain.time import ensure_utc
from mistake_notebook_api.infrastructure.database.models import (
    OCRRunModel,
    ProblemPublicationModel,
    ProblemRegionCandidateSourceModel,
    ProblemRegionModel,
    ProblemRevisionModel,
    RegionCandidateModel,
    RegionDetectionRunModel,
    ReviewedProblemModel,
    ReviewStatusEventModel,
    SourceAssetModel,
)


def _required_utc(value: datetime) -> datetime:
    normalized = ensure_utc(value)
    if normalized is None:
        raise ValueError("Required datetime cannot be null")
    return normalized


def _asset(model: SourceAssetModel) -> SourceAsset:
    return SourceAsset(
        id=model.id,
        file_name=model.file_name,
        media_type=model.media_type,
        storage_key=model.storage_key,
        file_hash=model.file_hash,
        width=model.width,
        height=model.height,
        file_size=model.file_size,
        created_at=_required_utc(model.created_at),
    )


def _region(model: ProblemRegionModel, detection_candidate_ids: list[str]) -> ProblemRegion:
    return ProblemRegion(
        id=model.id,
        source_asset_id=model.source_asset_id,
        page_number=model.page_number,
        x=model.x,
        y=model.y,
        width=model.width,
        height=model.height,
        coordinate_system=model.coordinate_system,
        cropped_asset_key=model.cropped_asset_key,
        selection_source=RegionSelectionSource(model.selection_source),
        detection_candidate_id=model.detection_candidate_id,
        detection_candidate_ids=detection_candidate_ids,
        created_at=_required_utc(model.created_at),
    )


def _detection_run(model: RegionDetectionRunModel) -> RegionDetectionRun:
    return RegionDetectionRun(
        id=model.id,
        source_asset_id=model.source_asset_id,
        provider=model.provider,
        provider_model=model.provider_model,
        provider_version=model.provider_version,
        status=RegionDetectionRunStatus(model.status),
        error_code=model.error_code,
        raw_response_storage_key=model.raw_response_storage_key,
        warnings=model.warnings_json,
        started_at=_required_utc(model.started_at),
        finished_at=_required_utc(model.finished_at),
        processing_time_ms=model.processing_time_ms,
    )


def _candidate(model: RegionCandidateModel) -> RegionCandidate:
    return RegionCandidate(
        id=model.id,
        detection_run_id=model.detection_run_id,
        provider_candidate_id=model.provider_candidate_id,
        x=model.x,
        y=model.y,
        width=model.width,
        height=model.height,
        coordinate_system=model.coordinate_system,
        confidence=model.confidence,
        reading_order=model.reading_order,
        metadata=model.metadata_json,
        created_at=_required_utc(model.created_at),
    )


def _ocr_run(model: OCRRunModel) -> OCRRun:
    return OCRRun(
        id=model.id,
        problem_region_id=model.problem_region_id,
        provider=model.provider,
        provider_model=model.provider_model,
        provider_version=model.provider_version,
        raw_response=model.raw_response,
        extracted_text=model.extracted_text,
        confidence=model.confidence,
        blocks=model.blocks_json,
        warnings=model.warnings_json,
        status=OCRRunStatus(model.status),
        error_code=model.error_code,
        started_at=_required_utc(model.started_at),
        finished_at=ensure_utc(model.finished_at),
        processing_time_ms=model.processing_time_ms,
    )


def _revision(model: ProblemRevisionModel) -> ProblemRevision:
    return ProblemRevision(
        id=model.id,
        problem_region_id=model.problem_region_id,
        based_on_ocr_run_id=model.based_on_ocr_run_id,
        revision_number=model.revision_number,
        corrected_text=model.corrected_text,
        correction_note=model.correction_note,
        created_at=_required_utc(model.created_at),
    )


def _problem(model: ReviewedProblemModel) -> ReviewedProblem:
    return ReviewedProblem(
        id=model.id,
        problem_region_id=model.problem_region_id,
        current_revision_id=model.current_revision_id,
        review_status=ReviewStatus(model.review_status),
        reviewed_at=ensure_utc(model.reviewed_at),
        created_at=_required_utc(model.created_at),
        updated_at=_required_utc(model.updated_at),
    )


def _event(model: ReviewStatusEventModel) -> ReviewStatusEvent:
    return ReviewStatusEvent(
        id=model.id,
        reviewed_problem_id=model.reviewed_problem_id,
        from_status=ReviewStatus(model.from_status) if model.from_status else None,
        to_status=ReviewStatus(model.to_status),
        reason=model.reason,
        ocr_run_id=model.ocr_run_id,
        revision_id=model.revision_id,
        created_at=_required_utc(model.created_at),
    )


def _publication(model: ProblemPublicationModel) -> ProblemPublication:
    return ProblemPublication(
        id=model.id,
        reviewed_problem_id=model.reviewed_problem_id,
        source_asset_id=model.source_asset_id,
        publisher=model.publisher,
        status=PublicationStatus(model.status),
        published_revision_id=model.published_revision_id,
        base_name=model.base_name,
        pages_table_id=model.pages_table_id,
        questions_table_id=model.questions_table_id,
        page_record_id=model.page_record_id,
        question_record_id=model.question_record_id,
        error_code=model.error_code,
        started_at=_required_utc(model.started_at),
        finished_at=ensure_utc(model.finished_at),
        updated_at=_required_utc(model.updated_at),
    )


class SQLAlchemySourceAssetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, asset: SourceAsset) -> None:
        self._session.add(SourceAssetModel(**asdict(asset)))

    def get(self, asset_id: str) -> SourceAsset | None:
        model = self._session.get(SourceAssetModel, asset_id)
        return _asset(model) if model else None

    def find_first_by_hash(self, file_hash: str) -> SourceAsset | None:
        model = self._session.scalar(
            select(SourceAssetModel)
            .where(SourceAssetModel.file_hash == file_hash)
            .order_by(SourceAssetModel.created_at, SourceAssetModel.id)
            .limit(1)
        )
        return _asset(model) if model else None


class SQLAlchemyRegionDetectionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_run(self, run: RegionDetectionRun) -> None:
        values = asdict(run)
        values["status"] = run.status.value
        values["warnings_json"] = values.pop("warnings")
        self._session.add(RegionDetectionRunModel(**values))
        self._session.flush()

    def get_run(self, run_id: str) -> RegionDetectionRun | None:
        model = self._session.get(RegionDetectionRunModel, run_id)
        return _detection_run(model) if model else None

    def add_candidate(self, candidate: RegionCandidate) -> None:
        values = asdict(candidate)
        values["metadata_json"] = values.pop("metadata")
        self._session.add(RegionCandidateModel(**values))

    def get_candidate(self, candidate_id: str) -> RegionCandidate | None:
        model = self._session.get(RegionCandidateModel, candidate_id)
        return _candidate(model) if model else None

    def list_candidates(self, run_id: str) -> list[RegionCandidate]:
        models = self._session.scalars(
            select(RegionCandidateModel)
            .where(RegionCandidateModel.detection_run_id == run_id)
            .order_by(RegionCandidateModel.reading_order, RegionCandidateModel.id)
        ).all()
        return [_candidate(model) for model in models]


class SQLAlchemyProblemRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_region(self, region: ProblemRegion) -> None:
        values = asdict(region)
        values["selection_source"] = region.selection_source.value
        candidate_ids = values.pop("detection_candidate_ids")
        expected_primary_id = candidate_ids[0] if candidate_ids else None
        if region.detection_candidate_id != expected_primary_id:
            raise ValueError("Primary detection candidate must be the first lineage candidate")
        self._session.add(ProblemRegionModel(**values))
        self._session.flush()
        self._session.add_all(
            [
                ProblemRegionCandidateSourceModel(
                    problem_region_id=region.id,
                    detection_candidate_id=candidate_id,
                    source_order=source_order,
                )
                for source_order, candidate_id in enumerate(candidate_ids)
            ]
        )

    def get_region(self, region_id: str) -> ProblemRegion | None:
        model = self._session.get(ProblemRegionModel, region_id)
        if model is None:
            return None
        candidate_ids = list(
            self._session.scalars(
                select(ProblemRegionCandidateSourceModel.detection_candidate_id)
                .where(ProblemRegionCandidateSourceModel.problem_region_id == region_id)
                .order_by(ProblemRegionCandidateSourceModel.source_order)
            ).all()
        )
        return _region(model, candidate_ids)

    def get_region_by_detection_candidate(self, candidate_id: str) -> ProblemRegion | None:
        model = self._session.scalar(
            select(ProblemRegionModel)
            .join(
                ProblemRegionCandidateSourceModel,
                ProblemRegionCandidateSourceModel.problem_region_id == ProblemRegionModel.id,
            )
            .where(ProblemRegionCandidateSourceModel.detection_candidate_id == candidate_id)
        )
        if model is None:
            return None
        return self.get_region(model.id)

    def add_problem(self, problem: ReviewedProblem) -> None:
        values = asdict(problem)
        values["review_status"] = problem.review_status.value
        self._session.add(ReviewedProblemModel(**values))
        # These aggregate rows have no ORM relationships by design; flush the
        # region/problem pair before an event references the problem.
        self._session.flush()

    def get_problem(self, problem_id: str) -> ReviewedProblem | None:
        model = self._session.get(ReviewedProblemModel, problem_id)
        return _problem(model) if model else None

    def get_problem_by_region(self, region_id: str) -> ReviewedProblem | None:
        model = self._session.scalar(
            select(ReviewedProblemModel).where(ReviewedProblemModel.problem_region_id == region_id)
        )
        return _problem(model) if model else None

    def list_problem_ids_by_asset(self, asset_id: str) -> list[str]:
        return list(
            self._session.scalars(
                select(ReviewedProblemModel.id)
                .join(
                    ProblemRegionModel,
                    ProblemRegionModel.id == ReviewedProblemModel.problem_region_id,
                )
                .where(ProblemRegionModel.source_asset_id == asset_id)
                .order_by(
                    ProblemRegionModel.y,
                    ProblemRegionModel.x,
                    ReviewedProblemModel.id,
                )
            ).all()
        )

    def update_problem(
        self,
        problem_id: str,
        *,
        current_revision_id: str | None,
        review_status: ReviewStatus,
        reviewed_at: datetime | None,
        updated_at: datetime,
    ) -> ReviewedProblem:
        model = self._session.get(ReviewedProblemModel, problem_id)
        if model is None:
            raise LookupError(problem_id)
        model.current_revision_id = current_revision_id
        model.review_status = review_status.value
        model.reviewed_at = reviewed_at
        model.updated_at = updated_at
        self._session.flush()
        return _problem(model)

    def add_ocr_run(self, run: OCRRun) -> None:
        values = asdict(run)
        values["status"] = run.status.value
        values["blocks_json"] = values.pop("blocks")
        values["warnings_json"] = values.pop("warnings")
        self._session.add(OCRRunModel(**values))

    def get_ocr_run(self, run_id: str) -> OCRRun | None:
        model = self._session.get(OCRRunModel, run_id)
        return _ocr_run(model) if model else None

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
    ) -> OCRRun:
        model = self._session.get(OCRRunModel, run_id)
        if model is None:
            raise LookupError(run_id)
        if model.status != OCRRunStatus.RUNNING.value:
            raise RuntimeError(f"OCR run is already terminal: {run_id}")
        model.status = status.value
        model.provider_model = provider_model
        model.provider_version = provider_version
        model.raw_response = raw_response
        model.extracted_text = extracted_text
        model.confidence = confidence
        model.blocks_json = blocks
        model.warnings_json = warnings
        model.error_code = error_code
        model.finished_at = finished_at
        model.processing_time_ms = processing_time_ms
        self._session.flush()
        return _ocr_run(model)

    def list_ocr_runs(self, region_id: str) -> list[OCRRun]:
        models = self._session.scalars(
            select(OCRRunModel)
            .where(OCRRunModel.problem_region_id == region_id)
            .order_by(OCRRunModel.started_at, OCRRunModel.id)
        ).all()
        return [_ocr_run(model) for model in models]

    def add_revision(self, revision: ProblemRevision) -> None:
        self._session.add(ProblemRevisionModel(**asdict(revision)))
        # Ensure the immutable revision exists before current_revision_id is updated.
        self._session.flush()

    def get_revision(self, revision_id: str) -> ProblemRevision | None:
        model = self._session.get(ProblemRevisionModel, revision_id)
        return _revision(model) if model else None

    def next_revision_number(self, region_id: str) -> int:
        maximum = self._session.scalar(
            select(func.max(ProblemRevisionModel.revision_number)).where(
                ProblemRevisionModel.problem_region_id == region_id
            )
        )
        return int(maximum or 0) + 1

    def list_revisions(self, region_id: str) -> list[ProblemRevision]:
        models = self._session.scalars(
            select(ProblemRevisionModel)
            .where(ProblemRevisionModel.problem_region_id == region_id)
            .order_by(ProblemRevisionModel.revision_number)
        ).all()
        return [_revision(model) for model in models]

    def add_status_event(self, event: ReviewStatusEvent) -> None:
        values = asdict(event)
        values["from_status"] = event.from_status.value if event.from_status else None
        values["to_status"] = event.to_status.value
        self._session.add(ReviewStatusEventModel(**values))

    def list_status_events(self, problem_id: str) -> list[ReviewStatusEvent]:
        models = self._session.scalars(
            select(ReviewStatusEventModel)
            .where(ReviewStatusEventModel.reviewed_problem_id == problem_id)
            .order_by(ReviewStatusEventModel.created_at, ReviewStatusEventModel.id)
        ).all()
        return [_event(model) for model in models]


class SQLAlchemyProblemPublicationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, publication: ProblemPublication) -> None:
        values = asdict(publication)
        values["status"] = publication.status.value
        self._session.add(ProblemPublicationModel(**values))

    def get_by_problem(self, problem_id: str) -> ProblemPublication | None:
        model = self._session.scalar(
            select(ProblemPublicationModel).where(
                ProblemPublicationModel.reviewed_problem_id == problem_id
            )
        )
        return _publication(model) if model else None

    def update(self, publication: ProblemPublication) -> None:
        model = self._session.get(ProblemPublicationModel, publication.id)
        if model is None:
            raise LookupError(publication.id)
        model.source_asset_id = publication.source_asset_id
        model.publisher = publication.publisher
        model.status = publication.status.value
        model.published_revision_id = publication.published_revision_id
        model.base_name = publication.base_name
        model.pages_table_id = publication.pages_table_id
        model.questions_table_id = publication.questions_table_id
        model.page_record_id = publication.page_record_id
        model.question_record_id = publication.question_record_id
        model.error_code = publication.error_code
        model.started_at = publication.started_at
        model.finished_at = publication.finished_at
        model.updated_at = publication.updated_at
        self._session.flush()
