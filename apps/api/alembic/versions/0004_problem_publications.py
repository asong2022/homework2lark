"""Track explicit publication of reviewed problems.

Revision ID: 0004_problem_publications
Revises: 0003_multi_candidate_lineage
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_problem_publications"
down_revision: str | None = "0003_multi_candidate_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "problem_publications",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("reviewed_problem_id", sa.String(length=64), nullable=False),
        sa.Column("source_asset_id", sa.String(length=64), nullable=False),
        sa.Column("publisher", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("published_revision_id", sa.String(length=64), nullable=False),
        sa.Column("base_name", sa.String(length=255), nullable=False),
        sa.Column("pages_table_id", sa.String(length=128), nullable=True),
        sa.Column("questions_table_id", sa.String(length=128), nullable=True),
        sa.Column("page_record_id", sa.String(length=128), nullable=True),
        sa.Column("question_record_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_problem_publications_status_valid",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND finished_at IS NULL AND error_code IS NULL) OR "
            "(status = 'succeeded' AND finished_at IS NOT NULL AND error_code IS NULL "
            "AND pages_table_id IS NOT NULL AND questions_table_id IS NOT NULL "
            "AND page_record_id IS NOT NULL AND question_record_id IS NOT NULL) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND error_code IS NOT NULL)",
            name="ck_problem_publications_terminal_fields_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["published_revision_id"],
            ["problem_revisions.id"],
            name="fk_problem_publications_published_revision_id_problem_revisions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_problem_id"],
            ["reviewed_problems.id"],
            name="fk_problem_publications_reviewed_problem_id_reviewed_problems",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["source_assets.id"],
            name="fk_problem_publications_source_asset_id_source_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_problem_publications"),
        sa.UniqueConstraint(
            "reviewed_problem_id", name="uq_problem_publications_reviewed_problem_id"
        ),
    )
    op.create_index(
        "ix_problem_publications_published_revision_id",
        "problem_publications",
        ["published_revision_id"],
        unique=False,
    )
    op.create_index(
        "ix_problem_publications_source_asset_id",
        "problem_publications",
        ["source_asset_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_problem_publications_source_asset_id", table_name="problem_publications")
    op.drop_index(
        "ix_problem_publications_published_revision_id",
        table_name="problem_publications",
    )
    op.drop_table("problem_publications")
