"""background budget

Revision ID: d4236aefe2d0
Revises: 71d583d62096
Create Date: 2026-10-07 22:02:36.588170

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4236aefe2d0"
down_revision: str | Sequence[str] | None = "71d583d62096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "llm_usage", sa.Column("background", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(
        "tenants",
        sa.Column("background_daily_tokens", sa.Integer(), server_default="100000", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_tenants_background_daily_tokens"), "tenants", "background_daily_tokens >= 0"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_tenants_background_daily_tokens"), "tenants", type_="check")
    op.drop_column("tenants", "background_daily_tokens")
    op.drop_column("llm_usage", "background")
