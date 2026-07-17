from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from pydantic.alias_generators import to_camel

from mistake_notebook_api.application.records import (
    BatchRegionCreateResult,
    NormalizedProblemView,
    RegionCreateResult,
    RegionDetectionView,
)
from mistake_notebook_api.domain.entities import (
    OCRRun,
    ProblemPublication,
    ProblemRegion,
    ProblemRevision,
    RegionCandidate,
    SourceAsset,
)
from mistake_notebook_api.domain.enums import (
    OCRBlockType,
    OCRRunStatus,
    PublicationStatus,
    RegionDetectionRunStatus,
    RegionSelectionSource,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        allow_inf_nan=False,
    )


class NormalizedBBoxRequest(ApiModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class RegionCreateRequest(ApiModel):
    coordinate_system: Literal["normalized_top_left"]
    bbox: NormalizedBBoxRequest


DetectionCandidateId = Annotated[str, Field(min_length=1, max_length=64)]


class RegionSelectionRequest(ApiModel):
    selection_source: RegionSelectionSource
    bbox: NormalizedBBoxRequest
    detection_candidate_ids: list[DetectionCandidateId] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        if self.selection_source is RegionSelectionSource.MANUAL and self.detection_candidate_ids:
            raise ValueError("manual selections cannot reference detection candidates")
        if (
            self.selection_source is RegionSelectionSource.DETECTED
            and not self.detection_candidate_ids
        ):
            raise ValueError("detected selections require detection candidates")
        if len(self.detection_candidate_ids) != len(set(self.detection_candidate_ids)):
            raise ValueError("detection candidate IDs must be unique within one problem")
        return self


class BatchRegionCreateRequest(ApiModel):
    coordinate_system: Literal["normalized_top_left"]
    regions: list[RegionSelectionRequest] = Field(min_length=1, max_length=100)


class RevisionCreateRequest(ApiModel):
    based_on_ocr_run_id: str = Field(min_length=1, max_length=64)
    corrected_text: str = Field(min_length=1, max_length=50_000)
    correction_note: str | None = Field(default=None, max_length=2_000)


class PixelBBoxResponse(ApiModel):
    x: int
    y: int
    width: int
    height: int


class NormalizedBBoxResponse(ApiModel):
    x: float
    y: float
    width: float
    height: float


class SourceAssetResponse(ApiModel):
    asset_id: str
    file_name: str
    media_type: str
    storage_key: str
    file_hash: str
    width: int
    height: int
    file_size: int
    content_url: str
    duplicate_of_asset_id: str | None = None
    created_at: datetime

    @classmethod
    def from_entity(cls, asset: SourceAsset, *, duplicate_of_asset_id: str | None = None) -> Self:
        return cls(
            asset_id=asset.id,
            file_name=asset.file_name,
            media_type=asset.media_type,
            storage_key=asset.storage_key,
            file_hash=asset.file_hash,
            width=asset.width,
            height=asset.height,
            file_size=asset.file_size,
            content_url=f"/api/v1/assets/{asset.id}/content",
            duplicate_of_asset_id=duplicate_of_asset_id,
            created_at=asset.created_at,
        )


class ProblemRegionResponse(ApiModel):
    region_id: str
    page_number: int
    coordinate_system: str
    bbox: PixelBBoxResponse
    cropped_asset_key: str
    crop_content_url: str
    selection_source: RegionSelectionSource
    detection_candidate_id: str | None
    detection_candidate_ids: list[str]
    created_at: datetime

    @classmethod
    def from_entity(cls, region: ProblemRegion) -> Self:
        return cls(
            region_id=region.id,
            page_number=region.page_number,
            coordinate_system=region.coordinate_system,
            bbox=PixelBBoxResponse(
                x=region.x, y=region.y, width=region.width, height=region.height
            ),
            cropped_asset_key=region.cropped_asset_key,
            crop_content_url=f"/api/v1/regions/{region.id}/crop",
            selection_source=region.selection_source,
            detection_candidate_id=region.detection_candidate_id,
            detection_candidate_ids=region.detection_candidate_ids,
            created_at=region.created_at,
        )


class RegionCreateResponse(ApiModel):
    region_id: str
    problem_id: str
    coordinate_system: str
    bbox: PixelBBoxResponse
    crop_content_url: str
    selection_source: RegionSelectionSource
    detection_candidate_id: str | None
    detection_candidate_ids: list[str]
    created_at: datetime

    @classmethod
    def from_result(cls, result: RegionCreateResult) -> Self:
        region = result.region
        return cls(
            region_id=region.id,
            problem_id=result.problem.id,
            coordinate_system=region.coordinate_system,
            bbox=PixelBBoxResponse(
                x=region.x, y=region.y, width=region.width, height=region.height
            ),
            crop_content_url=f"/api/v1/regions/{region.id}/crop",
            selection_source=region.selection_source,
            detection_candidate_id=region.detection_candidate_id,
            detection_candidate_ids=region.detection_candidate_ids,
            created_at=region.created_at,
        )


class BatchRegionCreateResponse(ApiModel):
    created_count: int
    items: list[RegionCreateResponse]

    @classmethod
    def from_result(cls, result: BatchRegionCreateResult) -> Self:
        return cls(
            created_count=len(result.items),
            items=[RegionCreateResponse.from_result(item) for item in result.items],
        )


class RegionCandidateResponse(ApiModel):
    detection_candidate_id: str
    provider_candidate_id: str
    coordinate_system: str
    bbox: PixelBBoxResponse
    normalized_bbox: NormalizedBBoxResponse
    confidence: float | None
    reading_order: int
    metadata: dict[str, JsonValue]

    @classmethod
    def from_entity(
        cls,
        candidate: RegionCandidate,
        *,
        source_width: int,
        source_height: int,
    ) -> Self:
        return cls(
            detection_candidate_id=candidate.id,
            provider_candidate_id=candidate.provider_candidate_id,
            coordinate_system=candidate.coordinate_system,
            bbox=PixelBBoxResponse(
                x=candidate.x,
                y=candidate.y,
                width=candidate.width,
                height=candidate.height,
            ),
            normalized_bbox=NormalizedBBoxResponse(
                x=candidate.x / source_width,
                y=candidate.y / source_height,
                width=candidate.width / source_width,
                height=candidate.height / source_height,
            ),
            confidence=candidate.confidence,
            reading_order=candidate.reading_order,
            metadata=candidate.metadata,
        )


class RegionDetectionRunResponse(ApiModel):
    run_id: str
    provider: str
    model: str | None
    provider_version: str | None
    status: RegionDetectionRunStatus
    error_code: str | None
    candidates: list[RegionCandidateResponse]
    warnings: list[str]
    started_at: datetime
    finished_at: datetime
    processing_time_ms: int

    @classmethod
    def from_view(cls, view: RegionDetectionView) -> Self:
        return cls(
            run_id=view.run.id,
            provider=view.run.provider,
            model=view.run.provider_model,
            provider_version=view.run.provider_version,
            status=view.run.status,
            error_code=view.run.error_code,
            candidates=[
                RegionCandidateResponse.from_entity(
                    candidate,
                    source_width=view.source_width,
                    source_height=view.source_height,
                )
                for candidate in view.candidates
            ],
            warnings=view.run.warnings,
            started_at=view.run.started_at,
            finished_at=view.run.finished_at,
            processing_time_ms=view.run.processing_time_ms,
        )


class OCRBlockResponse(ApiModel):
    type: OCRBlockType
    text: str
    bbox: PixelBBoxResponse | None
    confidence: float | None
    reading_order: int
    metadata: dict[str, JsonValue]


class OCRRunResponse(ApiModel):
    run_id: str
    provider: str
    model: str | None
    provider_version: str | None
    text: str | None
    confidence: float | None
    status: OCRRunStatus
    error_code: str | None
    blocks: list[OCRBlockResponse]
    raw_response: JsonValue | None
    warnings: list[str]
    started_at: datetime
    finished_at: datetime | None
    processing_time_ms: int | None

    @classmethod
    def from_entity(cls, run: OCRRun) -> Self:
        return cls(
            run_id=run.id,
            provider=run.provider,
            model=run.provider_model,
            provider_version=run.provider_version,
            text=run.extracted_text,
            confidence=run.confidence,
            status=run.status,
            error_code=run.error_code,
            blocks=[OCRBlockResponse.model_validate(block) for block in run.blocks],
            raw_response=run.raw_response,
            warnings=run.warnings,
            started_at=run.started_at,
            finished_at=run.finished_at,
            processing_time_ms=run.processing_time_ms,
        )


class ProblemRevisionResponse(ApiModel):
    revision_id: str
    based_on_ocr_run_id: str
    revision_number: int
    corrected_text: str
    correction_note: str | None
    created_at: datetime

    @classmethod
    def from_entity(cls, revision: ProblemRevision) -> Self:
        return cls(
            revision_id=revision.id,
            based_on_ocr_run_id=revision.based_on_ocr_run_id,
            revision_number=revision.revision_number,
            corrected_text=revision.corrected_text,
            correction_note=revision.correction_note,
            created_at=revision.created_at,
        )


class LineageResponse(ApiModel):
    source_asset_id: str
    problem_region_id: str
    detection_candidate_id: str | None
    detection_candidate_ids: list[str]
    ocr_run_id: str | None
    revision_id: str | None


class HistoryResponse(ApiModel):
    ocr_runs: list[OCRRunResponse]
    revisions: list[ProblemRevisionResponse]


class ProblemPublicationResponse(ApiModel):
    publication_id: str
    publisher: str
    status: PublicationStatus
    published_revision_id: str
    base_name: str
    pages_table_id: str | None
    questions_table_id: str | None
    page_record_id: str | None
    question_record_id: str | None
    error_code: str | None
    retryable: bool
    started_at: datetime
    finished_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_entity(cls, publication: ProblemPublication) -> Self:
        non_retryable_errors = {
            "configuration_error",
            "invalid_response",
            "duplicate_remote_record",
        }
        return cls(
            publication_id=publication.id,
            publisher=publication.publisher,
            status=publication.status,
            published_revision_id=publication.published_revision_id,
            base_name=publication.base_name,
            pages_table_id=publication.pages_table_id,
            questions_table_id=publication.questions_table_id,
            page_record_id=publication.page_record_id,
            question_record_id=publication.question_record_id,
            error_code=publication.error_code,
            retryable=(
                publication.status is PublicationStatus.FAILED
                and publication.error_code not in non_retryable_errors
            ),
            started_at=publication.started_at,
            finished_at=publication.finished_at,
            updated_at=publication.updated_at,
        )


class NormalizedProblemResponse(ApiModel):
    problem_id: str
    source: SourceAssetResponse
    region: ProblemRegionResponse
    ocr: OCRRunResponse | None
    latest_ocr_run: OCRRunResponse | None
    human_revision: ProblemRevisionResponse | None
    lineage: LineageResponse
    history: HistoryResponse
    publication: ProblemPublicationResponse | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view: NormalizedProblemView) -> Self:
        selected = (
            OCRRunResponse.from_entity(view.selected_ocr_run) if view.selected_ocr_run else None
        )
        latest = OCRRunResponse.from_entity(view.latest_ocr_run) if view.latest_ocr_run else None
        revision = (
            ProblemRevisionResponse.from_entity(view.current_revision)
            if view.current_revision
            else None
        )
        return cls(
            problem_id=view.problem.id,
            source=SourceAssetResponse.from_entity(view.source),
            region=ProblemRegionResponse.from_entity(view.region),
            ocr=selected,
            latest_ocr_run=latest,
            human_revision=revision,
            lineage=LineageResponse(
                source_asset_id=view.source.id,
                problem_region_id=view.region.id,
                detection_candidate_id=view.region.detection_candidate_id,
                detection_candidate_ids=view.region.detection_candidate_ids,
                ocr_run_id=view.selected_ocr_run.id if view.selected_ocr_run else None,
                revision_id=view.current_revision.id if view.current_revision else None,
            ),
            history=HistoryResponse(
                ocr_runs=[OCRRunResponse.from_entity(run) for run in view.ocr_runs],
                revisions=[ProblemRevisionResponse.from_entity(item) for item in view.revisions],
            ),
            publication=(
                ProblemPublicationResponse.from_entity(view.publication)
                if view.publication
                else None
            ),
            created_at=view.problem.created_at,
            updated_at=view.problem.updated_at,
        )


class AssetProblemCollectionResponse(ApiModel):
    asset_id: str
    count: int
    items: list[NormalizedProblemResponse]

    @classmethod
    def from_views(cls, asset_id: str, views: list[NormalizedProblemView]) -> Self:
        return cls(
            asset_id=asset_id,
            count=len(views),
            items=[NormalizedProblemResponse.from_view(view) for view in views],
        )


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, JsonValue]
    request_id: str
    retryable: bool


class ErrorEnvelope(ApiModel):
    error: ErrorBody


class HealthResponse(ApiModel):
    status: Literal["ok"]
    database: Literal["ok"]
    ocr_provider: str
    region_detection_provider: str
