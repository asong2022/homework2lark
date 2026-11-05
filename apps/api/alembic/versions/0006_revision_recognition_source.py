"""Record real recognition provenance without requiring an OCR run.

Revision ID: 0006_recognition_source
Revises: 0005_problem_assets
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_recognition_source"
down_revision: str | None = "0005_problem_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("problem_revisions") as batch:
        batch.add_column(
            sa.Column("recognition_source", sa.String(32), nullable=False, server_default="ocr")
        )
        batch.alter_column("based_on_ocr_run_id", existing_type=sa.String(64), nullable=True)
        batch.create_check_constraint(
            op.f("ck_problem_revisions_recognition_source_valid"),
            "recognition_source IN ('ocr', 'ai_vision', 'teacher')",
        )
        batch.create_check_constraint(
            op.f("ck_problem_revisions_recognition_ocr_basis"),
            "recognition_source != 'ocr' OR based_on_ocr_run_id IS NOT NULL",
        )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM problem_revisions WHERE recognition_source != 'ocr'")
    )
    if count:
        raise RuntimeError("Non-OCR revisions exist; downgrade would lose recognition evidence.")
    with op.batch_alter_table("problem_revisions") as batch:
        batch.drop_constraint(op.f("ck_problem_revisions_recognition_ocr_basis"), type_="check")
        batch.drop_constraint(op.f("ck_problem_revisions_recognition_source_valid"), type_="check")
        batch.drop_column("recognition_source")
        batch.alter_column("based_on_ocr_run_id", existing_type=sa.String(64), nullable=False)
