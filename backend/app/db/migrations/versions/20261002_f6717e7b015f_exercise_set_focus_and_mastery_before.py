"""exercise set focus and mastery before

Revision ID: f6717e7b015f
Revises: 9f45cf7f00b8
Create Date: 2026-10-02 16:43:29.618653

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6717e7b015f"
down_revision: str | Sequence[str] | None = "9f45cf7f00b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("exercise_sets", sa.Column("focus_kc_id", sa.String(length=100), nullable=True))
    op.add_column(
        "exercise_sets",
        sa.Column("mastery_before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exercise_sets", "mastery_before")
    op.drop_column("exercise_sets", "focus_kc_id")
