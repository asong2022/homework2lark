from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from mistake_notebook_api.application.ports import (
    ProblemPublicationRepository,
    ProblemRepository,
    RegionDetectionRepository,
    SourceAssetRepository,
    UnitOfWork,
)
from mistake_notebook_api.infrastructure.database.repositories import (
    SQLAlchemyProblemPublicationRepository,
    SQLAlchemyProblemRepository,
    SQLAlchemyRegionDetectionRepository,
    SQLAlchemySourceAssetRepository,
)


class SQLAlchemyUnitOfWork:
    assets: SourceAssetRepository
    detections: RegionDetectionRepository
    problems: ProblemRepository
    publications: ProblemPublicationRepository

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> SQLAlchemyUnitOfWork:
        self._session = self._session_factory()
        self.assets = SQLAlchemySourceAssetRepository(self._session)
        self.detections = SQLAlchemyRegionDetectionRepository(self._session)
        self.problems = SQLAlchemyProblemRepository(self._session)
        self.publications = SQLAlchemyProblemPublicationRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            self._session.rollback()
        self._session.close()
        self._session = None

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work is not active")
        self._session.commit()

    def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work is not active")
        self._session.rollback()


class SQLAlchemyUnitOfWorkFactory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> UnitOfWork:
        return SQLAlchemyUnitOfWork(self._session_factory)
