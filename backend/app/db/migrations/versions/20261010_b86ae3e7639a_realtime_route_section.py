"""realtime route section

Revision ID: b86ae3e7639a
Revises: 08753b283c97
Create Date: 2026-10-10 22:25:17.325593

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b86ae3e7639a"
down_revision: str | Sequence[str] | None = "08753b283c97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate doesn't compare CHECK constraints: realtime voice (ADR 0030 §2).
    _section_check("'llm', 'embedding', 'asr', 'tts', 'pronunciation', 'realtime'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM tenant_model_routes WHERE section = 'realtime'")
    _section_check("'llm', 'embedding', 'asr', 'tts', 'pronunciation'")


def _section_check(values: str) -> None:
    name = op.f("ck_tenant_model_routes_section")
    op.drop_constraint(name, "tenant_model_routes", type_="check")
    op.create_check_constraint(name, "tenant_model_routes", f"section IN ({values})")
