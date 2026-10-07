"""user background prefs

Revision ID: 94afd2b1f522
Revises: d4236aefe2d0
Create Date: 2026-10-07 22:09:15.671493

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "94afd2b1f522"
down_revision: str | Sequence[str] | None = "d4236aefe2d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_background_prefs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_background_prefs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "feature", name=op.f("pk_user_background_prefs")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user_background_prefs")
