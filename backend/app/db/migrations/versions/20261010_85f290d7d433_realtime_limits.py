"""realtime limits

Revision ID: 85f290d7d433
Revises: 48ef01baa0cf
Create Date: 2026-10-10 23:20:41.458684

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "85f290d7d433"
down_revision: str | Sequence[str] | None = "48ef01baa0cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Realtime voice limits (ADR 0030 §5); 0 turns calls off.
    for column, default in (("realtime_session_minutes", "15"), ("realtime_daily_minutes", "30")):
        op.add_column(
            "tenants", sa.Column(column, sa.Integer(), server_default=default, nullable=False)
        )
        op.create_check_constraint(op.f(f"ck_tenants_{column}"), "tenants", f"{column} >= 0")


def downgrade() -> None:
    """Downgrade schema."""
    for column in ("realtime_daily_minutes", "realtime_session_minutes"):
        op.drop_constraint(op.f(f"ck_tenants_{column}"), "tenants", type_="check")
        op.drop_column("tenants", column)
