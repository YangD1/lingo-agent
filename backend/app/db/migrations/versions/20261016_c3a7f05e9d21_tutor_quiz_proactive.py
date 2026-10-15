"""tutor quiz proactive (ADR 0046)

Revision ID: c3a7f05e9d21
Revises: b2e091212155
Create Date: 2026-10-16 10:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a7f05e9d21"
down_revision: str | Sequence[str] | None = "b2e091212155"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tutor_profiles",
        sa.Column("quiz_proactive", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tutor_profiles", "quiz_proactive")
