from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from mistake_notebook_api.application.detection_service import RegionDetectionService
from mistake_notebook_api.application.ports import UnitOfWorkFactory
from mistake_notebook_api.application.publication_service import ProblemPublicationService
from mistake_notebook_api.application.services import AssetService, ProblemWorkflowService
from mistake_notebook_api.config import Settings
from mistake_notebook_api.domain.detection import ProblemRegionDetectionProvider
from mistake_notebook_api.domain.errors import AppError
from mistake_notebook_api.domain.ocr import OCRProvider
from mistake_notebook_api.domain.publication import ProblemPublisher
from mistake_notebook_api.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
)
from mistake_notebook_api.infrastructure.database.uow import SQLAlchemyUnitOfWorkFactory
from mistake_notebook_api.infrastructure.detection.fake import (
    FakeProblemRegionDetectionProvider,
)
from mistake_notebook_api.infrastructure.ocr.fake import FakeOCRProvider
from mistake_notebook_api.infrastructure.ocr.paddle import PaddleOCRProvider
from mistake_notebook_api.infrastructure.ocr.paddle_vl_api import (
    PaddleOCRVLAPIProvider,
)
from mistake_notebook_api.infrastructure.publication.fake import FakeProblemPublisher
from mistake_notebook_api.infrastructure.publication.lark_cli import (
    LarkCliProblemPublisher,
    SubprocessLarkCliRunner,
)
from mistake_notebook_api.infrastructure.storage.local import LocalFileStorageAdapter
from mistake_notebook_api.infrastructure.yescan.client import YescanApiClient
from mistake_notebook_api.infrastructure.yescan.question_detection import (
    YescanQuestionDetectionProvider,
)


@dataclass(slots=True)
class Runtime:
    settings: Settings
    engine: Engine
    uow_factory: UnitOfWorkFactory
    storage: LocalFileStorageAdapter
    ocr_provider: OCRProvider
    region_detection_provider: ProblemRegionDetectionProvider
    problem_publisher: ProblemPublisher

    def asset_service(self) -> AssetService:
        return AssetService(
            uow_factory=self.uow_factory,
            storage=self.storage,
            settings=self.settings,
        )

    def problem_service(self) -> ProblemWorkflowService:
        return ProblemWorkflowService(
            uow_factory=self.uow_factory,
            storage=self.storage,
            ocr_provider=self.ocr_provider,
            settings=self.settings,
        )

    def region_detection_service(self) -> RegionDetectionService:
        return RegionDetectionService(
            uow_factory=self.uow_factory,
            storage=self.storage,
            provider=self.region_detection_provider,
        )

    def publication_service(self) -> ProblemPublicationService:
        return ProblemPublicationService(
            uow_factory=self.uow_factory,
            storage=self.storage,
            publisher=self.problem_publisher,
            base_name=self.settings.lark_base_title,
        )


def build_ocr_provider(settings: Settings) -> OCRProvider:
    if settings.ocr_provider == "fake":
        return FakeOCRProvider()
    if settings.ocr_provider == "paddleocr":
        return PaddleOCRProvider(
            language=settings.paddleocr_language,
            model_name=settings.paddleocr_model_name,
        )
    if settings.ocr_provider == "paddleocr_vl_api":
        return PaddleOCRVLAPIProvider(
            token=(
                settings.paddleocr_access_token.get_secret_value()
                if settings.paddleocr_access_token is not None
                else ""
            ),
            job_url=settings.paddleocr_api_job_url,
            model=settings.paddleocr_vl_model,
            request_timeout_seconds=settings.paddleocr_api_request_timeout_seconds,
            poll_interval_seconds=settings.paddleocr_api_poll_interval_seconds,
            poll_timeout_seconds=max(1, settings.ocr_timeout_seconds - 5),
        )
    raise AppError(
        "ocr_provider_configuration_error",
        "OCR_PROVIDER 必须是 fake、paddleocr 或 paddleocr_vl_api。",
    )


def build_region_detection_provider(settings: Settings) -> ProblemRegionDetectionProvider:
    if settings.region_detection_provider == "fake":
        return FakeProblemRegionDetectionProvider()
    if settings.region_detection_provider == "yescan":
        return YescanQuestionDetectionProvider(
            YescanApiClient(
                client_id=settings.yescan_api_key_id or "",
                client_secret=(
                    settings.yescan_api_key.get_secret_value()
                    if settings.yescan_api_key is not None
                    else ""
                ),
                endpoint=settings.yescan_api_base_url,
                timeout_seconds=settings.yescan_timeout_seconds,
            )
        )
    raise AppError(
        "region_detection_provider_configuration_error",
        "REGION_DETECTION_PROVIDER 必须是 fake 或 yescan。",
    )


def build_problem_publisher(settings: Settings) -> ProblemPublisher:
    if settings.problem_publisher == "fake":
        return FakeProblemPublisher()
    if settings.problem_publisher == "lark_cli":
        return LarkCliProblemPublisher(
            runner=SubprocessLarkCliRunner(
                command=settings.lark_cli_command,
                timeout_seconds=settings.lark_publish_timeout_seconds,
            ),
            base_title=settings.lark_base_title,
        )
    raise AppError(
        "lark_publisher_configuration_error",
        "PROBLEM_PUBLISHER 必须是 fake 或 lark_cli。",
    )


def build_runtime(settings: Settings) -> Runtime:
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    return Runtime(
        settings=settings,
        engine=engine,
        uow_factory=SQLAlchemyUnitOfWorkFactory(sessions),
        storage=LocalFileStorageAdapter(settings.storage_root),
        ocr_provider=build_ocr_provider(settings),
        region_detection_provider=build_region_detection_provider(settings),
        problem_publisher=build_problem_publisher(settings),
    )
