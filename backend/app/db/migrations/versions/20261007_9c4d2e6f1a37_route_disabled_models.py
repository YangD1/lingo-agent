"""route disabled models

Revision ID: 9c4d2e6f1a37
Revises: 5e1a7c3d9b20
Create Date: 2026-10-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c4d2e6f1a37"
down_revision: str | Sequence[str] | None = "5e1a7c3d9b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Models switched off in a tenant's route: kept in the chain, never called (ADR 0026).
    op.add_column(
        "tenant_model_routes",
        sa.Column(
            "disabled",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tenant_model_routes", "disabled")
