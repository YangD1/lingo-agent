"""gemini connection kind

Revision ID: 159018254c68
Revises: 85f290d7d433
Create Date: 2026-10-11 14:59:57.143658

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "159018254c68"
down_revision: str | Sequence[str] | None = "85f290d7d433"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "'deepseek', 'anthropic', 'openai', 'openai_compatible', 'azure_speech'"


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate doesn't compare CHECK constraints: Gemini Live calls (ADR 0030, Q61j).
    _kind_check(f"{OLD}, 'gemini'")


def downgrade() -> None:
    """Downgrade schema."""
    # Routes may still name the connection; they skip missing ones (ADR 0004).
    op.execute("DELETE FROM provider_connections WHERE kind = 'gemini'")
    _kind_check(OLD)


def _kind_check(values: str) -> None:
    name = op.f("ck_provider_connections_kind")
    op.drop_constraint(name, "provider_connections", type_="check")
    op.create_check_constraint(name, "provider_connections", f"kind IN ({values})")
