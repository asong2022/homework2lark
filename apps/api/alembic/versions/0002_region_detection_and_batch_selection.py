"""Add region detection evidence and selection lineage.

Revision ID: 0002_region_detection
Revises: 0001_phase_one
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_region_detection"
down_revision: str | None = "0001_phase_one"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "region_detection_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_asset_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_model", sa.String(length=128), nullable=True),
        sa.Column("provider_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("raw_response_storage_key", sa.String(length=512), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_time_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "processing_time_ms >= 0",
            name="ck_region_detection_runs_processing_time_non_negative",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_region_detection_runs_status_valid",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND error_code IS NULL "
            "AND raw_response_storage_key IS NOT NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL "
            "AND raw_response_storage_key IS NULL)",
            name="ck_region_detection_runs_terminal_fields_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["source_assets.id"],
            name="fk_region_detection_runs_source_asset_id_source_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_region_detection_runs"),
        sa.UniqueConstraint(
            "raw_response_storage_key",
            name="uq_region_detection_runs_raw_response_storage_key",
        ),
    )
    op.create_index(
        "ix_region_detection_runs_source_asset_id",
        "region_detection_runs",
        ["source_asset_id"],
    )

    op.create_table(
        "region_candidates",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("detection_run_id", sa.String(length=64), nullable=False),
        sa.Column("provider_candidate_id", sa.String(length=128), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("coordinate_system", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reading_order", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_region_candidates_confidence_range",
        ),
        sa.CheckConstraint("height > 0", name="ck_region_candidates_height_positive"),
        sa.CheckConstraint(
            "reading_order >= 0",
            name="ck_region_candidates_reading_order_non_negative",
        ),
        sa.CheckConstraint("width > 0", name="ck_region_candidates_width_positive"),
        sa.CheckConstraint("x >= 0", name="ck_region_candidates_x_non_negative"),
        sa.CheckConstraint("y >= 0", name="ck_region_candidates_y_non_negative"),
        sa.ForeignKeyConstraint(
            ["detection_run_id"],
            ["region_detection_runs.id"],
            name="fk_region_candidates_detection_run_id_region_detection_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_region_candidates"),
        sa.UniqueConstraint(
            "detection_run_id",
            "provider_candidate_id",
            name="uq_region_candidates_run_provider_candidate",
        ),
    )
    op.create_index(
        "ix_region_candidates_detection_run_id",
        "region_candidates",
        ["detection_run_id"],
    )

    with op.batch_alter_table("problem_regions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "selection_source",
                sa.String(length=32),
                nullable=False,
                server_default="manual",
            )
        )
        batch_op.add_column(
            sa.Column("detection_candidate_id", sa.String(length=64), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_problem_regions_selection_source_valid",
            "selection_source IN ('manual', 'detected')",
        )
        batch_op.create_check_constraint(
            "ck_problem_regions_selection_lineage_consistent",
            "(selection_source = 'manual' AND detection_candidate_id IS NULL) OR "
            "(selection_source = 'detected' AND detection_candidate_id IS NOT NULL)",
        )
        batch_op.create_foreign_key(
            "fk_problem_regions_detection_candidate_id_region_candidates",
            "region_candidates",
            ["detection_candidate_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_problem_regions_detection_candidate_id",
            ["detection_candidate_id"],
        )
        batch_op.create_index(
            "ix_problem_regions_detection_candidate_id",
            ["detection_candidate_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("problem_regions") as batch_op:
        batch_op.drop_index("ix_problem_regions_detection_candidate_id")
        batch_op.drop_constraint(
            "uq_problem_regions_detection_candidate_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_problem_regions_detection_candidate_id_region_candidates",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "ck_problem_regions_selection_lineage_consistent",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_problem_regions_selection_source_valid",
            type_="check",
        )
        batch_op.drop_column("detection_candidate_id")
        batch_op.drop_column("selection_source")

    op.drop_index("ix_region_candidates_detection_run_id", table_name="region_candidates")
    op.drop_table("region_candidates")
    op.drop_index(
        "ix_region_detection_runs_source_asset_id",
        table_name="region_detection_runs",
    )
    op.drop_table("region_detection_runs")
