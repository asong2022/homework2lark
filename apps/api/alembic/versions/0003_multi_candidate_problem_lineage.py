"""Allow one logical problem to preserve multiple detection candidates.

Revision ID: 0003_multi_candidate_lineage
Revises: 0002_region_detection
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_multi_candidate_lineage"
down_revision: str | None = "0002_region_detection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "problem_region_candidate_sources",
        sa.Column("problem_region_id", sa.String(length=64), nullable=False),
        sa.Column("detection_candidate_id", sa.String(length=64), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source_order >= 0",
            name="ck_problem_region_candidate_sources_source_order_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["detection_candidate_id"],
            ["region_candidates.id"],
            name=("fk_problem_region_candidate_sources_detection_candidate_id_region_candidates"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["problem_region_id"],
            ["problem_regions.id"],
            name=("fk_problem_region_candidate_sources_problem_region_id_problem_regions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "problem_region_id",
            "detection_candidate_id",
            name="pk_problem_region_candidate_sources",
        ),
        sa.UniqueConstraint(
            "detection_candidate_id",
            name="uq_problem_region_candidate_sources_detection_candidate_id",
        ),
        sa.UniqueConstraint(
            "problem_region_id",
            "source_order",
            name="uq_problem_region_candidate_sources_region_order",
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO problem_region_candidate_sources "
            "(problem_region_id, detection_candidate_id, source_order) "
            "SELECT id, detection_candidate_id, 0 FROM problem_regions "
            "WHERE detection_candidate_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_table("problem_region_candidate_sources")
