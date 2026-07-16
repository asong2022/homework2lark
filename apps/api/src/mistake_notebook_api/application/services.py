from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from time import perf_counter

from mistake_notebook_api.application.images import (
    NormalizedBoundingBox,
    crop_images,
    inspect_image,
    to_pixel_bbox,
)
from mistake_notebook_api.application.ports import UnitOfWorkFactory
from mistake_notebook_api.application.records import (
    AssetUploadResult,
    BatchRegionCreateResult,
    NormalizedProblemView,
    RegionCreateResult,
)
from mistake_notebook_api.config import Settings
from mistake_notebook_api.domain.entities import (
    OCRRun,
    ProblemRegion,
    ProblemRevision,
    ReviewedProblem,
    ReviewStatusEvent,
    SourceAsset,
)
from mistake_notebook_api.domain.enums import (
    OCRRunStatus,
    RegionSelectionSource,
    ReviewStatus,
)
from mistake_notebook_api.domain.errors import AppError, JsonValue, OCRProviderError
from mistake_notebook_api.domain.identifiers import new_id
from mistake_notebook_api.domain.ocr import OCRBlock, OCRInput, OCRProvider, OCRResult
from mistake_notebook_api.domain.review_rules import status_after_ocr
from mistake_notebook_api.domain.storage import StorageAdapter
from mistake_notebook_api.domain.time import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ProviderOutcome:
    result: OCRResult | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class RegionSelectionInput:
    selection_source: RegionSelectionSource
    normalized_bbox: NormalizedBoundingBox
    detection_candidate_ids: list[str]


def _recognize_with_timeout(
    provider: OCRProvider, input: OCRInput, *, timeout_seconds: int
) -> OCRResult:
    outcomes: Queue[_ProviderOutcome] = Queue(maxsize=1)

    def invoke_provider() -> None:
        try:
            outcome = _ProviderOutcome(result=provider.recognize(input))
        except Exception as error:
            outcome = _ProviderOutcome(error=error)
        outcomes.put_nowait(outcome)

    # Local OCR SDK calls are synchronous and do not expose cancellation. A daemon
    # thread lets the HTTP request honor its deadline; a late result has no database
    # callback and therefore cannot overwrite the terminal failed OCRRun.
    Thread(target=invoke_provider, name="ocr-provider-call", daemon=True).start()
    try:
        outcome = outcomes.get(timeout=timeout_seconds)
    except Empty:
        raise OCRProviderError("timeout") from None
    if outcome.error is not None:
        raise outcome.error
    if outcome.result is None:
        raise OCRProviderError("invalid_response")
    return outcome.result


def _safe_file_name(file_name: str | None) -> str:
    if not file_name:
        return "uploaded-image"
    sanitized = Path(file_name.replace("\\", "/")).name.strip()
    return sanitized[:255] or "uploaded-image"


def _block_json(block: OCRBlock) -> dict[str, JsonValue]:
    bbox: JsonValue = None
    if block.bbox is not None:
        bbox = {
            "x": block.bbox.x,
            "y": block.bbox.y,
            "width": block.bbox.width,
            "height": block.bbox.height,
        }
    return {
        "type": block.type.value,
        "text": block.text,
        "bbox": bbox,
        "confidence": block.confidence,
        "readingOrder": block.reading_order,
        "metadata": block.metadata,
    }


class AssetService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        storage: StorageAdapter,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._settings = settings

    def upload(self, *, file_name: str | None, data: bytes) -> AssetUploadResult:
        if len(data) > self._settings.max_upload_bytes:
            raise AppError("asset_too_large", "图片超过大小限制，请压缩后重试。")
        metadata = inspect_image(data, max_pixels=self._settings.max_image_pixels)
        created_at = utc_now()
        asset_id = new_id("asset")
        file_hash = hashlib.sha256(data).hexdigest()
        key = (
            f"sources/{created_at.year:04d}/{created_at.month:02d}/{asset_id}.{metadata.extension}"
        )
        asset = SourceAsset(
            id=asset_id,
            file_name=_safe_file_name(file_name),
            media_type=metadata.media_type,
            storage_key=key,
            file_hash=file_hash,
            width=metadata.width,
            height=metadata.height,
            file_size=len(data),
            created_at=created_at,
        )

        duplicate_id: str | None = None
        self._storage.write(key, data)
        try:
            with self._uow_factory() as uow:
                duplicate = uow.assets.find_first_by_hash(file_hash)
                duplicate_id = duplicate.id if duplicate else None
                uow.assets.add(asset)
                uow.commit()
        except Exception:
            self._compensate_file(key)
            raise

        logger.info(
            "source_asset_created asset_id=%s media_type=%s file_size=%s",
            asset.id,
            asset.media_type,
            asset.file_size,
        )
        return AssetUploadResult(asset, duplicate_id)

    def get(self, asset_id: str) -> SourceAsset:
        with self._uow_factory() as uow:
            asset = uow.assets.get(asset_id)
        if asset is None:
            raise AppError("asset_not_found", "找不到这份原始材料。")
        return asset

    def content(self, asset_id: str) -> tuple[SourceAsset, bytes]:
        asset = self.get(asset_id)
        return asset, self._storage.read(asset.storage_key)

    def _compensate_file(self, key: str) -> None:
        try:
            self._storage.delete(key)
        except AppError as error:
            logger.error(
                "storage_compensation_failed key_category=source exception_type=%s",
                type(error).__name__,
            )


class ProblemWorkflowService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        storage: StorageAdapter,
        ocr_provider: OCRProvider,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._ocr_provider = ocr_provider
        self._settings = settings

    def create_region(
        self, *, asset_id: str, normalized_bbox: NormalizedBoundingBox
    ) -> RegionCreateResult:
        result = self.create_regions_batch(
            asset_id=asset_id,
            selections=[
                RegionSelectionInput(
                    selection_source=RegionSelectionSource.MANUAL,
                    normalized_bbox=normalized_bbox,
                    detection_candidate_ids=[],
                )
            ],
        )
        return result.items[0]

    def create_regions_batch(
        self,
        *,
        asset_id: str,
        selections: list[RegionSelectionInput],
    ) -> BatchRegionCreateResult:
        if not selections:
            raise AppError("invalid_region_selection", "请至少选择一道题目。")

        ordered_selections = sorted(
            selections,
            key=lambda item: (
                item.normalized_bbox.y,
                item.normalized_bbox.x,
                item.normalized_bbox.height,
                item.normalized_bbox.width,
            ),
        )
        written_crop_keys: list[str] = []
        with self._uow_factory() as uow:
            asset = uow.assets.get(asset_id)
            if asset is None:
                raise AppError("asset_not_found", "找不到这份原始材料。")

            seen_candidates: set[str] = set()
            for selection in ordered_selections:
                candidate_ids = selection.detection_candidate_ids
                if selection.selection_source is RegionSelectionSource.MANUAL:
                    if candidate_ids:
                        raise AppError(
                            "invalid_region_selection",
                            "手动框题不能引用自动检测候选。",
                        )
                    continue
                if not candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
                    raise AppError(
                        "invalid_region_selection",
                        "自动候选引用无效或重复，请重新选择。",
                    )
                for candidate_id in candidate_ids:
                    if candidate_id in seen_candidates:
                        raise AppError(
                            "invalid_region_selection",
                            "同一个自动候选不能同时归入两道题。",
                        )
                    candidate = uow.detections.get_candidate(candidate_id)
                    detection_run = (
                        uow.detections.get_run(candidate.detection_run_id) if candidate else None
                    )
                    if (
                        candidate is None
                        or detection_run is None
                        or detection_run.source_asset_id != asset.id
                    ):
                        raise AppError(
                            "invalid_region_selection",
                            "自动候选不属于当前原图，请重新检测。",
                        )
                    if uow.problems.get_region_by_detection_candidate(candidate_id) is not None:
                        raise AppError(
                            "region_candidate_already_used",
                            "这个自动候选已经归入其他题目，请勿重复保存。",
                        )
                    seen_candidates.add(candidate_id)

            pixel_bboxes = [
                to_pixel_bbox(
                    selection.normalized_bbox,
                    source_width=asset.width,
                    source_height=asset.height,
                    min_region_pixels=self._settings.min_region_pixels,
                )
                for selection in ordered_selections
            ]
            source_bytes = self._storage.read(asset.storage_key)
            crop_payloads = crop_images(
                source_bytes,
                pixel_bboxes,
                expected_width=asset.width,
                expected_height=asset.height,
            )
            created_at = utc_now()
            results: list[RegionCreateResult] = []
            status_events: list[ReviewStatusEvent] = []
            crop_writes: list[tuple[str, bytes]] = []
            for selection, bbox, crop_bytes in zip(
                ordered_selections, pixel_bboxes, crop_payloads, strict=True
            ):
                region_id = new_id("region")
                problem_id = new_id("problem")
                crop_key = f"crops/{asset.id}/{region_id}.png"
                region = ProblemRegion(
                    id=region_id,
                    source_asset_id=asset.id,
                    page_number=1,
                    x=bbox.x,
                    y=bbox.y,
                    width=bbox.width,
                    height=bbox.height,
                    coordinate_system="pixel_top_left",
                    cropped_asset_key=crop_key,
                    selection_source=selection.selection_source,
                    detection_candidate_id=(
                        selection.detection_candidate_ids[0]
                        if selection.detection_candidate_ids
                        else None
                    ),
                    detection_candidate_ids=list(selection.detection_candidate_ids),
                    created_at=created_at,
                )
                problem = ReviewedProblem(
                    id=problem_id,
                    problem_region_id=region_id,
                    current_revision_id=None,
                    review_status=ReviewStatus.DRAFT,
                    reviewed_at=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
                results.append(RegionCreateResult(region, problem))
                status_events.append(
                    ReviewStatusEvent(
                        id=new_id("review_event"),
                        reviewed_problem_id=problem_id,
                        from_status=None,
                        to_status=ReviewStatus.DRAFT,
                        reason="region_created",
                        ocr_run_id=None,
                        revision_id=None,
                        created_at=created_at,
                    )
                )
                crop_writes.append((crop_key, crop_bytes))

            try:
                for crop_key, crop_bytes in crop_writes:
                    self._storage.write(crop_key, crop_bytes)
                    written_crop_keys.append(crop_key)
                for result, status_event in zip(results, status_events, strict=True):
                    uow.problems.add_region(result.region)
                    uow.problems.add_problem(result.problem)
                    uow.problems.add_status_event(status_event)
                uow.commit()
            except Exception:
                uow.rollback()
                for crop_key in written_crop_keys:
                    self._compensate_crop(crop_key)
                raise

        logger.info(
            "problem_regions_created asset_id=%s count=%s",
            asset_id,
            len(results),
        )
        return BatchRegionCreateResult(results)

    def crop_content(self, region_id: str) -> tuple[ProblemRegion, bytes]:
        with self._uow_factory() as uow:
            region = uow.problems.get_region(region_id)
        if region is None:
            raise AppError("region_not_found", "找不到这个题目区域。")
        if not self._storage.exists(region.cropped_asset_key):
            raise AppError("crop_not_found", "题目裁图不存在，请重新框选。")
        return region, self._storage.read(region.cropped_asset_key)

    def run_ocr(self, region_id: str) -> OCRRun:
        started_at = utc_now()
        run = OCRRun(
            id=new_id("ocr"),
            problem_region_id=region_id,
            provider=self._ocr_provider.name,
            provider_model=self._ocr_provider.model_name,
            provider_version=None,
            raw_response=None,
            extracted_text=None,
            confidence=None,
            blocks=[],
            warnings=[],
            status=OCRRunStatus.RUNNING,
            error_code=None,
            started_at=started_at,
            finished_at=None,
            processing_time_ms=None,
        )

        with self._uow_factory() as uow:
            region = uow.problems.get_region(region_id)
            if region is None:
                raise AppError("region_not_found", "找不到这个题目区域。")
            asset = uow.assets.get(region.source_asset_id)
            if asset is None:
                raise AppError("asset_not_found", "找不到这道题的原始材料。")
            uow.problems.add_ocr_run(run)
            uow.commit()

        invocation_started = perf_counter()
        try:
            crop_bytes = self._storage.read(region.cropped_asset_key)
            result = _recognize_with_timeout(
                self._ocr_provider,
                OCRInput(
                    source_asset_id=asset.id,
                    problem_region_id=region.id,
                    image_bytes=crop_bytes,
                    language=self._settings.paddleocr_language,
                ),
                timeout_seconds=self._settings.ocr_timeout_seconds,
            )
            return self._complete_ocr_success(run.id, result)
        except OCRProviderError as error:
            elapsed = max(1, round((perf_counter() - invocation_started) * 1000))
            self._complete_ocr_failure(run.id, error.category, elapsed)
            raise self._provider_app_error(error.category, run.id) from None
        except AppError:
            elapsed = max(1, round((perf_counter() - invocation_started) * 1000))
            self._complete_ocr_failure(run.id, "input_unavailable", elapsed)
            raise
        except Exception:
            elapsed = max(1, round((perf_counter() - invocation_started) * 1000))
            self._complete_ocr_failure(run.id, "unavailable", elapsed)
            raise AppError(
                "ocr_provider_unavailable",
                "OCR 服务暂时不可用，原图和题目区域已保存，可以稍后重试。",
                True,
                {"ocrRunId": run.id},
            ) from None

    def create_revision(
        self,
        *,
        region_id: str,
        based_on_ocr_run_id: str,
        corrected_text: str,
        correction_note: str | None,
    ) -> ProblemRevision:
        if not corrected_text.strip():
            raise AppError("revision_invalid", "人工修订文本不能为空。")
        created_at = utc_now()

        with self._uow_factory() as uow:
            region = uow.problems.get_region(region_id)
            if region is None:
                raise AppError("region_not_found", "找不到这个题目区域。")
            run = uow.problems.get_ocr_run(based_on_ocr_run_id)
            if (
                run is None
                or run.problem_region_id != region_id
                or run.status is not OCRRunStatus.SUCCEEDED
            ):
                raise AppError("ocr_run_invalid", "请选择属于这道题的有效 OCR 结果。")
            problem = uow.problems.get_problem_by_region(region_id)
            if problem is None:
                raise AppError("problem_not_found", "找不到这道题目记录。")
            revision = ProblemRevision(
                id=new_id("revision"),
                problem_region_id=region_id,
                based_on_ocr_run_id=based_on_ocr_run_id,
                revision_number=uow.problems.next_revision_number(region_id),
                corrected_text=corrected_text,
                correction_note=correction_note.strip() if correction_note else None,
                created_at=created_at,
            )
            uow.problems.add_revision(revision)
            previous_status = problem.review_status
            uow.problems.update_problem(
                problem.id,
                current_revision_id=revision.id,
                review_status=ReviewStatus.NEEDS_REVIEW,
                reviewed_at=None,
                updated_at=created_at,
            )
            if previous_status is not ReviewStatus.NEEDS_REVIEW:
                uow.problems.add_status_event(
                    self._status_event(
                        problem_id=problem.id,
                        from_status=previous_status,
                        to_status=ReviewStatus.NEEDS_REVIEW,
                        reason="revision_saved",
                        revision_id=revision.id,
                        created_at=created_at,
                    )
                )
            uow.commit()

        logger.info(
            "problem_revision_created region_id=%s revision_id=%s revision_number=%s",
            region_id,
            revision.id,
            revision.revision_number,
        )
        return revision

    def review(self, *, problem_id: str, revision_id: str) -> NormalizedProblemView:
        reviewed_at = utc_now()
        with self._uow_factory() as uow:
            problem = uow.problems.get_problem(problem_id)
            if problem is None:
                raise AppError("problem_not_found", "找不到这道题目记录。")
            revision = uow.problems.get_revision(revision_id)
            if (
                revision is None
                or revision.problem_region_id != problem.problem_region_id
                or not revision.corrected_text.strip()
            ):
                raise AppError("review_revision_required", "请先保存有效的人工修订版本。")
            if (
                problem.review_status is ReviewStatus.REVIEWED
                and problem.current_revision_id == revision_id
            ):
                return self.get_record(problem_id)
            previous_status = problem.review_status
            uow.problems.update_problem(
                problem.id,
                current_revision_id=revision.id,
                review_status=ReviewStatus.REVIEWED,
                reviewed_at=reviewed_at,
                updated_at=reviewed_at,
            )
            uow.problems.add_status_event(
                self._status_event(
                    problem_id=problem.id,
                    from_status=previous_status,
                    to_status=ReviewStatus.REVIEWED,
                    reason="teacher_reviewed",
                    revision_id=revision.id,
                    created_at=reviewed_at,
                )
            )
            uow.commit()

        logger.info("problem_reviewed problem_id=%s revision_id=%s", problem_id, revision_id)
        return self.get_record(problem_id)

    def get_record(self, problem_id: str) -> NormalizedProblemView:
        with self._uow_factory() as uow:
            problem = uow.problems.get_problem(problem_id)
            if problem is None:
                raise AppError("problem_not_found", "找不到这道题目记录。")
            region = uow.problems.get_region(problem.problem_region_id)
            if region is None:
                raise AppError("region_not_found", "找不到这道题的来源区域。")
            source = uow.assets.get(region.source_asset_id)
            if source is None:
                raise AppError("asset_not_found", "找不到这道题的原始材料。")
            runs = uow.problems.list_ocr_runs(region.id)
            revisions = uow.problems.list_revisions(region.id)
            events = uow.problems.list_status_events(problem.id)
            publication = uow.publications.get_by_problem(problem.id)

        current_revision = next(
            (item for item in revisions if item.id == problem.current_revision_id), None
        )
        selected_run: OCRRun | None = None
        if current_revision is not None:
            selected_run = next(
                (item for item in runs if item.id == current_revision.based_on_ocr_run_id),
                None,
            )
        if selected_run is None:
            selected_run = next(
                (item for item in reversed(runs) if item.status is OCRRunStatus.SUCCEEDED),
                runs[-1] if runs else None,
            )
        return NormalizedProblemView(
            problem=problem,
            source=source,
            region=region,
            selected_ocr_run=selected_run,
            latest_ocr_run=runs[-1] if runs else None,
            current_revision=current_revision,
            ocr_runs=runs,
            revisions=revisions,
            status_events=events,
            publication=publication,
        )

    def list_records_for_asset(self, asset_id: str) -> list[NormalizedProblemView]:
        with self._uow_factory() as uow:
            asset = uow.assets.get(asset_id)
            if asset is None:
                raise AppError("asset_not_found", "找不到这张原始图片。")
            problem_ids = uow.problems.list_problem_ids_by_asset(asset_id)

        return [self.get_record(problem_id) for problem_id in problem_ids]

    def _complete_ocr_success(self, run_id: str, result: OCRResult) -> OCRRun:
        if result.provider != self._ocr_provider.name:
            raise OCRProviderError("invalid_response")
        finished_at = utc_now()
        warnings = list(result.warnings)
        if not result.text.strip() and "ocr_empty_text" not in warnings:
            warnings.append("ocr_empty_text")
        blocks = [_block_json(block) for block in result.blocks]

        with self._uow_factory() as uow:
            current = uow.problems.get_ocr_run(run_id)
            if current is None:
                raise AppError("ocr_run_not_found", "找不到这次 OCR 运行记录。")
            completed = uow.problems.complete_ocr_run(
                run_id,
                status=OCRRunStatus.SUCCEEDED,
                provider_model=result.model,
                provider_version=result.provider_version,
                raw_response=result.raw_response,
                extracted_text=result.text,
                confidence=result.confidence,
                blocks=blocks,
                warnings=warnings,
                error_code=None,
                finished_at=finished_at,
                processing_time_ms=result.processing_time_ms,
            )
            problem = uow.problems.get_problem_by_region(current.problem_region_id)
            if problem is None:
                raise AppError("problem_not_found", "找不到这道题目记录。")
            next_status = status_after_ocr(problem.review_status, result.text)
            if next_status is not problem.review_status:
                uow.problems.update_problem(
                    problem.id,
                    current_revision_id=problem.current_revision_id,
                    review_status=next_status,
                    reviewed_at=problem.reviewed_at,
                    updated_at=finished_at,
                )
                uow.problems.add_status_event(
                    self._status_event(
                        problem_id=problem.id,
                        from_status=problem.review_status,
                        to_status=next_status,
                        reason="ocr_text_ready" if result.text.strip() else "ocr_empty",
                        ocr_run_id=run_id,
                        created_at=finished_at,
                    )
                )
            uow.commit()

        logger.info(
            "ocr_run_finished region_id=%s run_id=%s provider=%s status=succeeded "
            "processing_time_ms=%s text_length=%s",
            current.problem_region_id,
            run_id,
            self._ocr_provider.name,
            result.processing_time_ms,
            len(result.text),
        )
        return completed

    def _complete_ocr_failure(self, run_id: str, category: str, elapsed_ms: int) -> None:
        with self._uow_factory() as uow:
            run = uow.problems.get_ocr_run(run_id)
            if run is None or run.status is not OCRRunStatus.RUNNING:
                return
            uow.problems.complete_ocr_run(
                run_id,
                status=OCRRunStatus.FAILED,
                provider_model=run.provider_model,
                provider_version=None,
                raw_response={"errorCategory": category},
                extracted_text=None,
                confidence=None,
                blocks=[],
                warnings=[],
                error_code=category,
                finished_at=utc_now(),
                processing_time_ms=elapsed_ms,
            )
            uow.commit()
        logger.warning(
            "ocr_run_finished run_id=%s provider=%s status=failed error_code=%s",
            run_id,
            self._ocr_provider.name,
            category,
        )

    @staticmethod
    def _provider_app_error(category: str, run_id: str) -> AppError:
        details: dict[str, JsonValue] = {"ocrRunId": run_id}
        if category == "timeout":
            return AppError(
                "ocr_timeout",
                "OCR 识别超时，原图和题目区域已保存，可以重试。",
                True,
                details,
            )
        if category == "invalid_response":
            return AppError(
                "ocr_invalid_response",
                "OCR 返回了无法解析的结果，请稍后重试或检查 Provider。",
                True,
                details,
            )
        if category == "configuration_error":
            return AppError(
                "ocr_provider_configuration_error",
                "OCR Provider 尚未正确安装或配置。",
                False,
                details,
            )
        return AppError(
            "ocr_provider_unavailable",
            "OCR 服务暂时不可用，原图和题目区域已保存，可以稍后重试。",
            True,
            details,
        )

    @staticmethod
    def _status_event(
        *,
        problem_id: str,
        from_status: ReviewStatus,
        to_status: ReviewStatus,
        reason: str,
        created_at: datetime,
        ocr_run_id: str | None = None,
        revision_id: str | None = None,
    ) -> ReviewStatusEvent:
        if not hasattr(created_at, "tzinfo"):
            raise ValueError("created_at must be a datetime")
        return ReviewStatusEvent(
            id=new_id("review_event"),
            reviewed_problem_id=problem_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            ocr_run_id=ocr_run_id,
            revision_id=revision_id,
            created_at=created_at,
        )

    def _compensate_crop(self, key: str) -> None:
        try:
            self._storage.delete(key)
        except AppError as error:
            logger.error(
                "storage_compensation_failed key_category=crop exception_type=%s",
                type(error).__name__,
            )
