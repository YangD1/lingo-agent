"""review log format

Revision ID: dc7609c9257f
Revises: 159018254c68
Create Date: 2026-10-11 21:19:18.110807

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dc7609c9257f"
down_revision: str | Sequence[str] | None = "159018254c68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Earlier reviews all showed the word (task 63, Q63f).
    op.add_column(
        "review_logs",
        sa.Column("format", sa.String(length=10), server_default="recognize", nullable=False),
    )
    # Autogenerate doesn't compare CHECK constraints.
    op.create_check_constraint(
        op.f("ck_review_logs_format"), "review_logs", "format IN ('recognize', 'listen', 'spell')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("review_logs", "format")
