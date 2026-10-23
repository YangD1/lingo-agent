"""deepen settings

Revision ID: bb59951a4151
Revises: 8c3e5f1a2d47
Create Date: 2026-10-24 02:24:15.977742

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "bb59951a4151"
down_revision: str | Sequence[str] | None = "8c3e5f1a2d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Limits on the tutor's follow-up segments (ADR 0064 §5).
    op.add_column(
        "tenants",
        sa.Column(
            "deepen_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{"enabled":true,"max_segments":1,"first_chunk_seconds":15,"total_seconds":60,"max_tokens":1500}',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tenants", "deepen_settings")
