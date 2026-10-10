"""realtime call seconds

Revision ID: 48ef01baa0cf
Revises: b86ae3e7639a
Create Date: 2026-10-10 22:55:02.501651

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48ef01baa0cf"
down_revision: str | Sequence[str] | None = "b86ae3e7639a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # How long a realtime call has been connected (ADR 0030 §5).
    op.add_column(
        "speaking_sessions",
        sa.Column("call_seconds", sa.Float(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_speaking_sessions_call_seconds"), "speaking_sessions", "call_seconds >= 0"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("ck_speaking_sessions_call_seconds"), "speaking_sessions", type_="check"
    )
    op.drop_column("speaking_sessions", "call_seconds")
