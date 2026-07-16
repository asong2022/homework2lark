from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from mistake_notebook_api.domain.errors import JsonValue
from mistake_notebook_api.domain.time import utc_now
from mistake_notebook_api.infrastructure.database.base import Base


class SourceAssetModel(Base):
    __tablename__ = "source_assets"
    __table_args__ = (
        CheckConstraint("width > 0", name="width_positive"),
        CheckConstraint("height > 0", name="height_positive"),
        CheckConstraint("file_size > 0", name="file_size_positive"),
        Index("ix_source_assets_file_hash", "file_hash"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RegionDetectionRunModel(Base):
    __tablename__ = "region_detection_runs"
    __table_args__ = (
        CheckConstraint("status IN ('succeeded', 'failed')", name="status_valid"),
        CheckConstraint("processing_time_ms >= 0", name="processing_time_non_negative"),
        CheckConstraint(
            "(status = 'succeeded' AND error_code IS NULL "
            "AND raw_response_storage_key IS NOT NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL "
            "AND raw_response_storage_key IS NULL)",
            name="terminal_fields_consistent",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_asset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(128))
    provider_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    raw_response_storage_key: Mapped[str | None] = mapped_column(String(512), unique=True)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class RegionCandidateModel(Base):
    __tablename__ = "region_candidates"
    __table_args__ = (
        UniqueConstraint(
            "detection_run_id",
            "provider_candidate_id",
            name="uq_region_candidates_run_provider_candidate",
        ),
        CheckConstraint("x >= 0", name="x_non_negative"),
        CheckConstraint("y >= 0", name="y_non_negative"),
        CheckConstraint("width > 0", name="width_positive"),
        CheckConstraint("height > 0", name="height_positive"),
        CheckConstraint("reading_order >= 0", name="reading_order_non_negative"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    detection_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("region_detection_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    coordinate_system: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProblemRegionModel(Base):
    __tablename__ = "problem_regions"
    __table_args__ = (
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        CheckConstraint("x >= 0", name="x_non_negative"),
        CheckConstraint("y >= 0", name="y_non_negative"),
        CheckConstraint("width > 0", name="width_positive"),
        CheckConstraint("height > 0", name="height_positive"),
        CheckConstraint(
            "selection_source IN ('manual', 'detected')",
            name="selection_source_valid",
        ),
        CheckConstraint(
            "(selection_source = 'manual' AND detection_candidate_id IS NULL) OR "
            "(selection_source = 'detected' AND detection_candidate_id IS NOT NULL)",
            name="selection_lineage_consistent",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    coordinate_system: Mapped[str] = mapped_column(String(32), nullable=False)
    cropped_asset_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    selection_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual"
    )
    detection_candidate_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("region_candidates.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProblemRegionCandidateSourceModel(Base):
    __tablename__ = "problem_region_candidate_sources"
    __table_args__ = (
        CheckConstraint("source_order >= 0", name="source_order_non_negative"),
        UniqueConstraint(
            "detection_candidate_id",
            name="uq_problem_region_candidate_sources_detection_candidate_id",
        ),
        UniqueConstraint(
            "problem_region_id",
            "source_order",
            name="uq_problem_region_candidate_sources_region_order",
        ),
    )

    problem_region_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("problem_regions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    detection_candidate_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("region_candidates.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)


class OCRRunModel(Base):
    __tablename__ = "ocr_runs"
    __table_args__ = (
        UniqueConstraint("problem_region_id", "id", name="uq_ocr_runs_region_id_id"),
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status_valid"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "processing_time_ms IS NULL OR processing_time_ms >= 0",
            name="processing_time_non_negative",
        ),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND error_code IS NULL) OR "
            "(status = 'succeeded' AND finished_at IS NOT NULL AND error_code IS NULL) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND error_code IS NOT NULL)",
            name="terminal_fields_consistent",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    problem_region_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("problem_regions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(128))
    provider_version: Mapped[str | None] = mapped_column(String(64))
    raw_response: Mapped[JsonValue | None] = mapped_column(JSON)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    blocks_json: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)


class ProblemRevisionModel(Base):
    __tablename__ = "problem_revisions"
    __table_args__ = (
        UniqueConstraint("problem_region_id", "id", name="uq_problem_revisions_region_id_id"),
        UniqueConstraint(
            "problem_region_id",
            "revision_number",
            name="uq_problem_revisions_region_revision_number",
        ),
        ForeignKeyConstraint(
            ["problem_region_id", "based_on_ocr_run_id"],
            ["ocr_runs.problem_region_id", "ocr_runs.id"],
            ondelete="RESTRICT",
            name="fk_problem_revisions_region_ocr_run",
        ),
        CheckConstraint("revision_number >= 1", name="revision_number_positive"),
        CheckConstraint("length(trim(corrected_text)) > 0", name="corrected_text_non_empty"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    problem_region_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("problem_regions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    based_on_ocr_run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    correction_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ReviewedProblemModel(Base):
    __tablename__ = "reviewed_problems"
    __table_args__ = (
        ForeignKeyConstraint(
            ["problem_region_id", "current_revision_id"],
            ["problem_revisions.problem_region_id", "problem_revisions.id"],
            ondelete="RESTRICT",
            name="fk_reviewed_problems_region_current_revision",
        ),
        CheckConstraint(
            "review_status IN ('draft', 'ocr_completed', 'needs_review', 'reviewed')",
            name="review_status_valid",
        ),
        CheckConstraint(
            "(review_status = 'reviewed' AND current_revision_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL) OR "
            "(review_status != 'reviewed' AND reviewed_at IS NULL)",
            name="reviewed_fields_consistent",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    problem_region_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("problem_regions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    current_revision_id: Mapped[str | None] = mapped_column(String(64))
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ReviewStatusEventModel(Base):
    __tablename__ = "review_status_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('draft', 'ocr_completed', 'needs_review', 'reviewed')",
            name="from_status_valid",
        ),
        CheckConstraint(
            "to_status IN ('draft', 'ocr_completed', 'needs_review', 'reviewed')",
            name="to_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reviewed_problem_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reviewed_problems.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    ocr_run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ocr_runs.id", ondelete="RESTRICT"), index=True
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("problem_revisions.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProblemPublicationModel(Base):
    __tablename__ = "problem_publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="status_valid",
        ),
        CheckConstraint(
            "(status = 'pending' AND finished_at IS NULL AND error_code IS NULL) OR "
            "(status = 'succeeded' AND finished_at IS NOT NULL AND error_code IS NULL "
            "AND pages_table_id IS NOT NULL AND questions_table_id IS NOT NULL "
            "AND page_record_id IS NOT NULL AND question_record_id IS NOT NULL) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND error_code IS NOT NULL)",
            name="terminal_fields_consistent",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reviewed_problem_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reviewed_problems.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    source_asset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    publisher: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    published_revision_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("problem_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    base_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pages_table_id: Mapped[str | None] = mapped_column(String(128))
    questions_table_id: Mapped[str | None] = mapped_column(String(128))
    page_record_id: Mapped[str | None] = mapped_column(String(128))
    question_record_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
