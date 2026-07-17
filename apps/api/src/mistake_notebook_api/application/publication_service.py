from __future__ import annotations

import logging
from dataclasses import replace

from mistake_notebook_api.application.ports import UnitOfWorkFactory
from mistake_notebook_api.domain.entities import ProblemPublication
from mistake_notebook_api.domain.enums import PublicationStatus
from mistake_notebook_api.domain.errors import AppError, JsonValue
from mistake_notebook_api.domain.identifiers import new_id
from mistake_notebook_api.domain.publication import (
    ProblemPublicationRequest,
    ProblemPublisher,
    ProblemPublisherError,
)
from mistake_notebook_api.domain.storage import StorageAdapter
from mistake_notebook_api.domain.time import utc_now

logger = logging.getLogger(__name__)


class ProblemPublicationService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        storage: StorageAdapter,
        publisher: ProblemPublisher,
        base_name: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._publisher = publisher
        self._base_name = base_name

    def publish(self, problem_id: str) -> ProblemPublication:
        request = self._build_request(problem_id)
        started_at = utc_now()

        with self._uow_factory() as uow:
            current = uow.publications.get_by_problem(problem_id)
            publication = ProblemPublication(
                id=current.id if current else new_id("publication"),
                problem_id=problem_id,
                source_asset_id=request.source_asset_id,
                publisher=self._publisher.name,
                status=PublicationStatus.PENDING,
                published_revision_id=request.revision_id,
                base_name=self._base_name,
                pages_table_id=current.pages_table_id if current else None,
                questions_table_id=current.questions_table_id if current else None,
                page_record_id=current.page_record_id if current else None,
                question_record_id=current.question_record_id if current else None,
                error_code=None,
                started_at=started_at,
                finished_at=None,
                updated_at=started_at,
            )
            if current is None:
                uow.publications.add(publication)
            else:
                uow.publications.update(publication)
            uow.commit()

        try:
            result = self._publisher.publish(request)
        except ProblemPublisherError as error:
            failed = self._finish_failed(publication, error.category)
            raise self._app_error(error.category, failed.id) from None
        except Exception:
            failed = self._finish_failed(publication, "unavailable")
            raise self._app_error("unavailable", failed.id) from None

        finished_at = utc_now()
        succeeded = replace(
            publication,
            status=PublicationStatus.SUCCEEDED,
            base_name=result.base_name,
            pages_table_id=result.pages_table_id,
            questions_table_id=result.questions_table_id,
            page_record_id=result.page_record_id,
            question_record_id=result.question_record_id,
            error_code=None,
            finished_at=finished_at,
            updated_at=finished_at,
        )
        with self._uow_factory() as uow:
            uow.publications.update(succeeded)
            uow.commit()
        logger.info(
            "problem_publication_finished problem_id=%s publication_id=%s "
            "publisher=%s status=succeeded",
            problem_id,
            succeeded.id,
            self._publisher.name,
        )
        return succeeded

    def _build_request(self, problem_id: str) -> ProblemPublicationRequest:
        with self._uow_factory() as uow:
            problem = uow.problems.get_problem(problem_id)
            if problem is None or problem.current_revision_id is None:
                raise AppError(
                    "problem_not_publishable",
                    "请先保存有效的教师修订，再发布到飞书。",
                )
            region = uow.problems.get_region(problem.problem_region_id)
            revision = uow.problems.get_revision(problem.current_revision_id)
            if (
                region is None
                or revision is None
                or revision.problem_region_id != problem.problem_region_id
                or not revision.corrected_text.strip()
            ):
                raise AppError(
                    "problem_not_publishable",
                    "当前人工修订不完整，请重新保存后再发布。",
                )
            source = uow.assets.get(region.source_asset_id)
            run = uow.problems.get_ocr_run(revision.based_on_ocr_run_id)
            if source is None or run is None:
                raise AppError(
                    "problem_not_publishable",
                    "题目来源或 OCR 依据不完整，暂时不能发布。",
                )

        return ProblemPublicationRequest(
            source_asset_id=source.id,
            source_file_hash=source.file_hash,
            source_file_name=source.file_name,
            source_media_type=source.media_type,
            source_image_bytes=self._storage.read(source.storage_key),
            problem_id=problem.id,
            problem_region_id=region.id,
            page_number=region.page_number,
            crop_image_bytes=self._storage.read(region.cropped_asset_key),
            revision_id=revision.id,
            revision_number=revision.revision_number,
            corrected_text=revision.corrected_text,
            revision_created_at=revision.created_at,
            ocr_provider=run.provider,
        )

    def _finish_failed(self, publication: ProblemPublication, category: str) -> ProblemPublication:
        finished_at = utc_now()
        failed = replace(
            publication,
            status=PublicationStatus.FAILED,
            error_code=category,
            finished_at=finished_at,
            updated_at=finished_at,
        )
        with self._uow_factory() as uow:
            uow.publications.update(failed)
            uow.commit()
        logger.warning(
            "problem_publication_finished problem_id=%s publication_id=%s "
            "publisher=%s status=failed error_code=%s",
            publication.problem_id,
            publication.id,
            self._publisher.name,
            category,
        )
        return failed

    @staticmethod
    def _app_error(category: str, publication_id: str) -> AppError:
        details: dict[str, JsonValue] = {"publicationId": publication_id}
        if category == "configuration_error":
            return AppError(
                "lark_publisher_configuration_error",
                "飞书发布尚未正确配置，请检查 lark-cli 登录和 Base 字段。",
                False,
                details,
            )
        if category in {"invalid_response", "duplicate_remote_record"}:
            return AppError(
                "lark_publisher_invalid_response",
                "飞书返回的数据不符合发布契约，请检查是否存在重复同步 ID。",
                False,
                details,
            )
        return AppError(
            "lark_publisher_unavailable",
            "飞书暂时不可用，本地题目和人工修订已保留，可以稍后重试。",
            True,
            details,
        )
