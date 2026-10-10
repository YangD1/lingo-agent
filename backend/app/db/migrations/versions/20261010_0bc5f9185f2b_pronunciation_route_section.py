"""pronunciation route section

Revision ID: 0bc5f9185f2b
Revises: ef6b9eccf722
Create Date: 2026-10-10 12:04:56.487149

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0bc5f9185f2b"
down_revision: str | Sequence[str] | None = "ef6b9eccf722"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate doesn't compare CHECK constraints: pronunciation assessment (ADR 0028 §5).
    _section_check("'llm', 'embedding', 'asr', 'tts', 'pronunciation'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM tenant_model_routes WHERE section = 'pronunciation'")
    _section_check("'llm', 'embedding', 'asr', 'tts'")


def _section_check(values: str) -> None:
    name = op.f("ck_tenant_model_routes_section")
    op.drop_constraint(name, "tenant_model_routes", type_="check")
    op.create_check_constraint(name, "tenant_model_routes", f"section IN ({values})")
