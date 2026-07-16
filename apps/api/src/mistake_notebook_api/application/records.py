from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class AssetUploadResult:
    asset: SourceAsset
    duplicate_of_asset_id: str | None


@dataclass(frozen=True, slots=True)
class RegionCreateResult:
    region: ProblemRegion
    problem: ReviewedProblem


@dataclass(frozen=True, slots=True)
class BatchRegionCreateResult:
    items: list[RegionCreateResult]


@dataclass(frozen=True, slots=True)
class RegionDetectionView:
    run: RegionDetectionRun
    candidates: list[RegionCandidate]
    source_width: int
    source_height: int


@dataclass(frozen=True, slots=True)
class NormalizedProblemView:
    problem: ReviewedProblem
    source: SourceAsset
    region: ProblemRegion
    selected_ocr_run: OCRRun | None
    latest_ocr_run: OCRRun | None
    current_revision: ProblemRevision | None
    ocr_runs: list[OCRRun]
    revisions: list[ProblemRevision]
    status_events: list[ReviewStatusEvent]
    publication: ProblemPublication | None
