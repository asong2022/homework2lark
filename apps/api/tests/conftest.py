from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mistake_notebook_api.api.runtime import Runtime
from mistake_notebook_api.config import Settings
from mistake_notebook_api.infrastructure.database.base import Base
from mistake_notebook_api.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
)
from mistake_notebook_api.infrastructure.database.uow import SQLAlchemyUnitOfWorkFactory
from mistake_notebook_api.infrastructure.detection.fake import (
    FakeProblemRegionDetectionProvider,
)
from mistake_notebook_api.infrastructure.ocr.fake import FakeOCRProvider
from mistake_notebook_api.infrastructure.publication.fake import FakeProblemPublisher
from mistake_notebook_api.infrastructure.storage.local import LocalFileStorageAdapter
from mistake_notebook_api.main import create_app


def image_bytes(
    image_format: str = "PNG", *, size: tuple[int, int] = (120, 80), color: str = "white"
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color=color).save(output, format=image_format)
    return output.getvalue()


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[Runtime]:
    database = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite:///{database.as_posix()}",
        storage_root=tmp_path / "storage",
        max_upload_bytes=2 * 1024 * 1024,
        max_image_pixels=1_000_000,
        min_region_pixels=2,
        cors_origins="http://localhost:3000",
        ocr_provider="fake",
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    value = Runtime(
        settings=settings,
        engine=engine,
        uow_factory=SQLAlchemyUnitOfWorkFactory(sessions),
        storage=LocalFileStorageAdapter(settings.storage_root),
        ocr_provider=FakeOCRProvider(),
        region_detection_provider=FakeProblemRegionDetectionProvider(),
        problem_publisher=FakeProblemPublisher(),
    )
    yield value
    engine.dispose()


@pytest.fixture
def client(runtime: Runtime) -> Iterator[TestClient]:
    with TestClient(
        create_app(settings=runtime.settings, runtime=runtime),
        raise_server_exceptions=False,
    ) as test_client:
        yield test_client
