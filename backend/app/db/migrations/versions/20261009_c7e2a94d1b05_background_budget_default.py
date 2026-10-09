"""background_budget_default

Revision ID: c7e2a94d1b05
Revises: 16aa2f30597e
Create Date: 2026-10-09 18:30:00.000000

A new tenant's daily background budget: 100,000 -> 300,000 tokens (task 49.3, from
the real-model run of 49.2). Existing tenants keep the value they have.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e2a94d1b05"
down_revision: str | Sequence[str] | None = "16aa2f30597e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tenants", "background_daily_tokens", server_default="300000")


def downgrade() -> None:
    op.alter_column("tenants", "background_daily_tokens", server_default="100000")
