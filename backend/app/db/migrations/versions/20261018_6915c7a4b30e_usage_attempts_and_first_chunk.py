"""usage attempts and first chunk

Revision ID: 6915c7a4b30e
Revises: 8d4ebcf8f132
Create Date: 2026-10-18 19:23:01.652375

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6915c7a4b30e"
down_revision: str | Sequence[str] | None = "8d4ebcf8f132"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Each try of a request, and when its first chunk arrived (ADR 0056 §5).
    op.add_column("llm_usage", sa.Column("first_chunk_ms", sa.Integer(), nullable=True))
    op.add_column(
        "llm_usage", sa.Column("attempt", sa.SmallInteger(), server_default="1", nullable=False)
    )
    # Autogenerate doesn't compare CHECK constraints.
    _status_check("'ok', 'error', 'cancelled', 'stalled'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE llm_usage SET status = 'error' WHERE status IN ('cancelled', 'stalled')")
    _status_check("'ok', 'error'")
    op.drop_column("llm_usage", "attempt")
    op.drop_column("llm_usage", "first_chunk_ms")


def _status_check(values: str) -> None:
    name = op.f("ck_llm_usage_status")
    op.drop_constraint(name, "llm_usage", type_="check")
    op.create_check_constraint(name, "llm_usage", f"status IN ({values})")
