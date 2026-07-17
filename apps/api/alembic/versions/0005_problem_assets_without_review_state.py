"""Replace reviewed-problem state with a current-revision problem asset.

Revision ID: 0005_problem_assets
Revises: 0004_problem_publications
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_problem_assets"
down_revision: str | None = "0004_problem_publications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _publication_columns(*, problem_column: str) -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(problem_column, sa.String(length=64), nullable=False),
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
    ]


def _publication_checks(*, suffix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name=f"ck_problem_publications_status_valid{suffix}",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND finished_at IS NULL AND error_code IS NULL) OR "
            "(status = 'succeeded' AND finished_at IS NOT NULL AND error_code IS NULL "
            "AND pages_table_id IS NOT NULL AND questions_table_id IS NOT NULL "
            "AND page_record_id IS NOT NULL AND question_record_id IS NOT NULL) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND error_code IS NOT NULL)",
            name=f"ck_problem_publications_terminal_fields_consistent{suffix}",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "problem_assets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("problem_region_id", sa.String(length=64), nullable=False),
        sa.Column("current_revision_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["problem_region_id", "current_revision_id"],
            ["problem_revisions.problem_region_id", "problem_revisions.id"],
            name="fk_problem_assets_region_current_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["problem_region_id"],
            ["problem_regions.id"],
            name="fk_problem_assets_problem_region_id_problem_regions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_problem_assets"),
        sa.UniqueConstraint("problem_region_id", name="uq_problem_assets_problem_region_id"),
    )
    op.execute(
        "INSERT INTO problem_assets "
        "(id, problem_region_id, current_revision_id, created_at, updated_at) "
        "SELECT id, problem_region_id, current_revision_id, created_at, updated_at "
        "FROM reviewed_problems"
    )

    op.create_table(
        "problem_publications_v2",
        *_publication_columns(problem_column="problem_id"),
        *_publication_checks(suffix="_v2"),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["problem_assets.id"],
            name="fk_problem_publications_v2_problem_id_problem_assets",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_revision_id"],
            ["problem_revisions.id"],
            name="fk_problem_publications_v2_published_revision_id_problem_revisions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["source_assets.id"],
            name="fk_problem_publications_v2_source_asset_id_source_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_problem_publications_v2"),
        sa.UniqueConstraint("problem_id", name="uq_problem_publications_v2_problem_id"),
    )
    op.execute(
        "INSERT INTO problem_publications_v2 "
        "(id, problem_id, source_asset_id, publisher, status, published_revision_id, "
        "base_name, pages_table_id, questions_table_id, page_record_id, question_record_id, "
        "error_code, started_at, finished_at, updated_at) "
        "SELECT id, reviewed_problem_id, source_asset_id, publisher, status, "
        "published_revision_id, base_name, pages_table_id, questions_table_id, "
        "page_record_id, question_record_id, error_code, started_at, finished_at, updated_at "
        "FROM problem_publications"
    )
    op.drop_index("ix_problem_publications_source_asset_id", table_name="problem_publications")
    op.drop_index(
        "ix_problem_publications_published_revision_id",
        table_name="problem_publications",
    )
    op.drop_table("problem_publications")

    op.drop_index(
        "ix_review_status_events_reviewed_problem_id",
        table_name="review_status_events",
    )
    op.drop_index("ix_review_status_events_revision_id", table_name="review_status_events")
    op.drop_index("ix_review_status_events_ocr_run_id", table_name="review_status_events")
    op.drop_table("review_status_events")
    op.drop_table("reviewed_problems")

    op.rename_table("problem_publications_v2", "problem_publications")
    op.create_index(
        "ix_problem_publications_published_revision_id",
        "problem_publications",
        ["published_revision_id"],
    )
    op.create_index(
        "ix_problem_publications_source_asset_id",
        "problem_publications",
        ["source_asset_id"],
    )


def downgrade() -> None:
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
    op.execute(
        "INSERT INTO reviewed_problems "
        "(id, problem_region_id, current_revision_id, review_status, reviewed_at, "
        "created_at, updated_at) "
        "SELECT id, problem_region_id, current_revision_id, "
        "CASE WHEN current_revision_id IS NULL THEN 'draft' ELSE 'reviewed' END, "
        "CASE WHEN current_revision_id IS NULL THEN NULL ELSE updated_at END, "
        "created_at, updated_at FROM problem_assets"
    )

    op.create_table(
        "problem_publications_v1",
        *_publication_columns(problem_column="reviewed_problem_id"),
        *_publication_checks(suffix="_v1"),
        sa.ForeignKeyConstraint(
            ["reviewed_problem_id"],
            ["reviewed_problems.id"],
            name="fk_problem_publications_v1_reviewed_problem_id_reviewed_problems",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_revision_id"],
            ["problem_revisions.id"],
            name="fk_problem_publications_v1_published_revision_id_problem_revisions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["source_assets.id"],
            name="fk_problem_publications_v1_source_asset_id_source_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_problem_publications_v1"),
        sa.UniqueConstraint(
            "reviewed_problem_id",
            name="uq_problem_publications_v1_reviewed_problem_id",
        ),
    )
    op.execute(
        "INSERT INTO problem_publications_v1 "
        "(id, reviewed_problem_id, source_asset_id, publisher, status, "
        "published_revision_id, base_name, pages_table_id, questions_table_id, "
        "page_record_id, question_record_id, error_code, started_at, finished_at, updated_at) "
        "SELECT id, problem_id, source_asset_id, publisher, status, published_revision_id, "
        "base_name, pages_table_id, questions_table_id, page_record_id, question_record_id, "
        "error_code, started_at, finished_at, updated_at FROM problem_publications"
    )
    op.drop_index("ix_problem_publications_source_asset_id", table_name="problem_publications")
    op.drop_index(
        "ix_problem_publications_published_revision_id",
        table_name="problem_publications",
    )
    op.drop_table("problem_publications")
    op.drop_table("problem_assets")
    op.rename_table("problem_publications_v1", "problem_publications")
    op.create_index(
        "ix_problem_publications_published_revision_id",
        "problem_publications",
        ["published_revision_id"],
    )
    op.create_index(
        "ix_problem_publications_source_asset_id",
        "problem_publications",
        ["source_asset_id"],
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
    op.create_index(
        "ix_review_status_events_revision_id",
        "review_status_events",
        ["revision_id"],
    )
    op.create_index(
        "ix_review_status_events_reviewed_problem_id",
        "review_status_events",
        ["reviewed_problem_id"],
    )
