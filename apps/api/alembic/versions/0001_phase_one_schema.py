"""Create the Phase 1 problem lineage schema.

Revision ID: 0001_phase_one
Revises:
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase_one"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_assets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("file_size > 0", name="ck_source_assets_file_size_positive"),
        sa.CheckConstraint("height > 0", name="ck_source_assets_height_positive"),
        sa.CheckConstraint("width > 0", name="ck_source_assets_width_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_source_assets"),
        sa.UniqueConstraint("storage_key", name="uq_source_assets_storage_key"),
    )
    op.create_index("ix_source_assets_file_hash", "source_assets", ["file_hash"])

    op.create_table(
        "problem_regions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_asset_id", sa.String(length=64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("coordinate_system", sa.String(length=32), nullable=False),
        sa.Column("cropped_asset_key", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("height > 0", name="ck_problem_regions_height_positive"),
        sa.CheckConstraint("page_number >= 1", name="ck_problem_regions_page_number_positive"),
        sa.CheckConstraint("width > 0", name="ck_problem_regions_width_positive"),
        sa.CheckConstraint("x >= 0", name="ck_problem_regions_x_non_negative"),
        sa.CheckConstraint("y >= 0", name="ck_problem_regions_y_non_negative"),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["source_assets.id"],
            name="fk_problem_regions_source_asset_id_source_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_problem_regions"),
        sa.UniqueConstraint("cropped_asset_key", name="uq_problem_regions_cropped_asset_key"),
    )
    op.create_index("ix_problem_regions_source_asset_id", "problem_regions", ["source_asset_id"])

    op.create_table(
        "ocr_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("problem_region_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_model", sa.String(length=128), nullable=True),
        sa.Column("provider_version", sa.String(length=64), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("blocks_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ocr_runs_confidence_range",
        ),
        sa.CheckConstraint(
            "processing_time_ms IS NULL OR processing_time_ms >= 0",
            name="ck_ocr_runs_processing_time_non_negative",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_ocr_runs_status_valid",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND error_code IS NULL) OR "
            "(status = 'succeeded' AND finished_at IS NOT NULL AND error_code IS NULL) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND error_code IS NOT NULL)",
            name="ck_ocr_runs_terminal_fields_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["problem_region_id"],
            ["problem_regions.id"],
            name="fk_ocr_runs_problem_region_id_problem_regions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ocr_runs"),
        sa.UniqueConstraint("problem_region_id", "id", name="uq_ocr_runs_region_id_id"),
    )
    op.create_index("ix_ocr_runs_problem_region_id", "ocr_runs", ["problem_region_id"])

    op.create_table(
        "problem_revisions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("problem_region_id", sa.String(length=64), nullable=False),
        sa.Column("based_on_ocr_run_id", sa.String(length=64), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=False),
        sa.Column("correction_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(corrected_text)) > 0",
            name="ck_problem_revisions_corrected_text_non_empty",
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_problem_revisions_revision_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["problem_region_id", "based_on_ocr_run_id"],
            ["ocr_runs.problem_region_id", "ocr_runs.id"],
            name="fk_problem_revisions_region_ocr_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["problem_region_id"],
            ["problem_regions.id"],
            name="fk_problem_revisions_problem_region_id_problem_regions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_problem_revisions"),
        sa.UniqueConstraint("problem_region_id", "id", name="uq_problem_revisions_region_id_id"),
        sa.UniqueConstraint(
            "problem_region_id",
            "revision_number",
            name="uq_problem_revisions_region_revision_number",
        ),
    )
    op.create_index(
        "ix_problem_revisions_based_on_ocr_run_id",
        "problem_revisions",
        ["based_on_ocr_run_id"],
    )
    op.create_index(
        "ix_problem_revisions_problem_region_id",
        "problem_revisions",
        ["problem_region_id"],
    )

    op.create_table(
        "reviewed_problems",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("problem_region_id", sa.String(length=64), nullable=False),
        sa.Column("current_revision_id", sa.String(length=64), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "review_status IN ('draft', 'ocr_completed', 'needs_review', 'reviewed')",
            name="ck_reviewed_problems_review_status_valid",
        ),
        sa.CheckConstraint(
            "(review_status = 'reviewed' AND current_revision_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL) OR "
            "(review_status != 'reviewed' AND reviewed_at IS NULL)",
            name="ck_reviewed_problems_reviewed_fields_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["problem_region_id", "current_revision_id"],
            ["problem_revisions.problem_region_id", "problem_revisions.id"],
            name="fk_reviewed_problems_region_current_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["problem_region_id"],
            ["problem_regions.id"],
            name="fk_reviewed_problems_problem_region_id_problem_regions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reviewed_problems"),
        sa.UniqueConstraint("problem_region_id", name="uq_reviewed_problems_problem_region_id"),
    )

    op.create_table(
        "review_status_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("reviewed_problem_id", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("ocr_run_id", sa.String(length=64), nullable=True),
        sa.Column("revision_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('draft', 'ocr_completed', 'needs_review', 'reviewed')",
            name="ck_review_status_events_from_status_valid",
        ),
        sa.CheckConstraint(
            "to_status IN ('draft', 'ocr_completed', 'needs_review', 'reviewed')",
            name="ck_review_status_events_to_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["ocr_run_id"],
            ["ocr_runs.id"],
            name="fk_review_status_events_ocr_run_id_ocr_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["problem_revisions.id"],
            name="fk_review_status_events_revision_id_problem_revisions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_problem_id"],
            ["reviewed_problems.id"],
            name="fk_review_status_events_reviewed_problem_id_reviewed_problems",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_status_events"),
    )
    op.create_index("ix_review_status_events_ocr_run_id", "review_status_events", ["ocr_run_id"])
    op.create_index("ix_review_status_events_revision_id", "review_status_events", ["revision_id"])
    op.create_index(
        "ix_review_status_events_reviewed_problem_id",
        "review_status_events",
        ["reviewed_problem_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_status_events_reviewed_problem_id",
        table_name="review_status_events",
    )
    op.drop_index("ix_review_status_events_revision_id", table_name="review_status_events")
    op.drop_index("ix_review_status_events_ocr_run_id", table_name="review_status_events")
    op.drop_table("review_status_events")
    op.drop_table("reviewed_problems")
    op.drop_index("ix_problem_revisions_problem_region_id", table_name="problem_revisions")
    op.drop_index("ix_problem_revisions_based_on_ocr_run_id", table_name="problem_revisions")
    op.drop_table("problem_revisions")
    op.drop_index("ix_ocr_runs_problem_region_id", table_name="ocr_runs")
    op.drop_table("ocr_runs")
    op.drop_index("ix_problem_regions_source_asset_id", table_name="problem_regions")
    op.drop_table("problem_regions")
    op.drop_index("ix_source_assets_file_hash", table_name="source_assets")
    op.drop_table("source_assets")
