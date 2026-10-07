"""scheduler runs

Revision ID: 71d583d62096
Revises: 9c4d2e6f1a37
Create Date: 2026-10-07 21:55:22.096734

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "71d583d62096"
down_revision: str | Sequence[str] | None = "9c4d2e6f1a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "scheduler_runs",
        sa.Column("job", sa.String(length=64), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=10), nullable=False),
        sa.Column("last_skip_reason", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "last_status IN ('running', 'ok', 'skipped', 'error')",
            name=op.f("ck_scheduler_runs_last_status"),
        ),
        sa.PrimaryKeyConstraint("job", name=op.f("pk_scheduler_runs")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scheduler_runs")
