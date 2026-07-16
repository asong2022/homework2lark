from __future__ import annotations

import json
import logging
from datetime import datetime
from time import perf_counter

from mistake_notebook_api.application.ports import UnitOfWorkFactory
from mistake_notebook_api.application.records import RegionDetectionView
from mistake_notebook_api.domain.detection import (
    ProblemRegionDetectionProvider,
    RegionDetectionInput,
)
from mistake_notebook_api.domain.entities import RegionCandidate, RegionDetectionRun
from mistake_notebook_api.domain.enums import RegionDetectionRunStatus
from mistake_notebook_api.domain.errors import (
    AppError,
    JsonValue,
    RegionDetectionProviderError,
)
from mistake_notebook_api.domain.identifiers import new_id
from mistake_notebook_api.domain.storage import StorageAdapter
from mistake_notebook_api.domain.time import utc_now

logger = logging.getLogger(__name__)


class RegionDetectionService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        storage: StorageAdapter,
        provider: ProblemRegionDetectionProvider,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._provider = provider

    def detect(self, asset_id: str) -> RegionDetectionView:
        with self._uow_factory() as uow:
            asset = uow.assets.get(asset_id)
        if asset is None:
            raise AppError("asset_not_found", "找不到这份原始材料。")

        source_bytes = self._storage.read(asset.storage_key)
        run_id = new_id("detection")
        started_at = utc_now()
        invocation_started = perf_counter()
        try:
            result = self._provider.detect(
                RegionDetectionInput(
                    source_asset_id=asset.id,
                    image_bytes=source_bytes,
                    width=asset.width,
                    height=asset.height,
                    media_type=asset.media_type,
                )
            )
            if result.provider != self._provider.name:
                raise RegionDetectionProviderError("invalid_response")
            evidence_bytes = json.dumps(
                result.raw_response,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except RegionDetectionProviderError as error:
            elapsed = max(1, round((perf_counter() - invocation_started) * 1000))
            self._persist_failed_run(
                run_id=run_id,
                asset_id=asset.id,
                error_code=error.category,
                started_at=started_at,
                processing_time_ms=elapsed,
            )
            raise self._provider_app_error(error.category, run_id) from None
        except (TypeError, ValueError):
            elapsed = max(1, round((perf_counter() - invocation_started) * 1000))
            self._persist_failed_run(
                run_id=run_id,
                asset_id=asset.id,
                error_code="invalid_response",
                started_at=started_at,
                processing_time_ms=elapsed,
            )
            raise self._provider_app_error("invalid_response", run_id) from None
        except Exception:
            elapsed = max(1, round((perf_counter() - invocation_started) * 1000))
            self._persist_failed_run(
                run_id=run_id,
                asset_id=asset.id,
                error_code="unavailable",
                started_at=started_at,
                processing_time_ms=elapsed,
            )
            raise self._provider_app_error("unavailable", run_id) from None

        finished_at = utc_now()
        evidence_key = f"provider-evidence/region-detections/{asset.id}/{run_id}.json"
        try:
            self._storage.write(evidence_key, evidence_bytes)
        except AppError:
            self._persist_failed_run(
                run_id=run_id,
                asset_id=asset.id,
                error_code="storage_unavailable",
                started_at=started_at,
                processing_time_ms=result.processing_time_ms,
            )
            raise

        run = RegionDetectionRun(
            id=run_id,
            source_asset_id=asset.id,
            provider=result.provider,
            provider_model=result.model,
            provider_version=result.provider_version,
            status=RegionDetectionRunStatus.SUCCEEDED,
            error_code=None,
            raw_response_storage_key=evidence_key,
            warnings=list(result.warnings),
            started_at=started_at,
            finished_at=finished_at,
            processing_time_ms=result.processing_time_ms,
        )
        candidates = [
            RegionCandidate(
                id=new_id("candidate"),
                detection_run_id=run.id,
                provider_candidate_id=candidate.provider_candidate_id,
                x=candidate.bbox.x,
                y=candidate.bbox.y,
                width=candidate.bbox.width,
                height=candidate.bbox.height,
                coordinate_system="pixel_top_left",
                confidence=candidate.confidence,
                reading_order=candidate.reading_order,
                metadata=candidate.metadata,
                created_at=finished_at,
            )
            for candidate in result.candidates
        ]
        try:
            with self._uow_factory() as uow:
                uow.detections.add_run(run)
                for candidate in candidates:
                    uow.detections.add_candidate(candidate)
                uow.commit()
        except Exception:
            self._compensate_evidence(evidence_key)
            raise

        logger.info(
            "region_detection_finished asset_id=%s run_id=%s provider=%s "
            "status=succeeded candidate_count=%s processing_time_ms=%s",
            asset.id,
            run.id,
            run.provider,
            len(candidates),
            run.processing_time_ms,
        )
        return RegionDetectionView(run, candidates, asset.width, asset.height)

    def _persist_failed_run(
        self,
        *,
        run_id: str,
        asset_id: str,
        error_code: str,
        started_at: datetime,
        processing_time_ms: int,
    ) -> None:
        finished_at = utc_now()
        run = RegionDetectionRun(
            id=run_id,
            source_asset_id=asset_id,
            provider=self._provider.name,
            provider_model=self._provider.model_name,
            provider_version=None,
            status=RegionDetectionRunStatus.FAILED,
            error_code=error_code,
            raw_response_storage_key=None,
            warnings=[],
            started_at=started_at,
            finished_at=finished_at,
            processing_time_ms=processing_time_ms,
        )
        with self._uow_factory() as uow:
            uow.detections.add_run(run)
            uow.commit()
        logger.warning(
            "region_detection_finished asset_id=%s run_id=%s provider=%s "
            "status=failed error_code=%s",
            asset_id,
            run_id,
            self._provider.name,
            error_code,
        )

    @staticmethod
    def _provider_app_error(category: str, run_id: str) -> AppError:
        details: dict[str, JsonValue] = {"detectionRunId": run_id}
        if category == "timeout":
            return AppError(
                "region_detection_timeout",
                "自动框题超时，原图已保存，仍可手动框题或稍后重试。",
                True,
                details,
            )
        if category == "invalid_response":
            return AppError(
                "region_detection_invalid_response",
                "自动框题返回了无法使用的坐标，仍可手动框题或重试。",
                True,
                details,
            )
        if category == "configuration_error":
            return AppError(
                "region_detection_provider_configuration_error",
                "自动框题 Provider 尚未正确配置，仍可手动框题。",
                False,
                details,
            )
        if category == "input_rejected":
            return AppError(
                "region_detection_input_rejected",
                "自动框题无法处理这张图片，仍可手动框题。",
                False,
                details,
            )
        return AppError(
            "region_detection_provider_unavailable",
            "自动框题服务暂时不可用，原图已保存，仍可手动框题或稍后重试。",
            True,
            details,
        )

    def _compensate_evidence(self, key: str) -> None:
        try:
            self._storage.delete(key)
        except AppError as error:
            logger.error(
                "storage_compensation_failed key_category=provider_evidence exception_type=%s",
                type(error).__name__,
            )
