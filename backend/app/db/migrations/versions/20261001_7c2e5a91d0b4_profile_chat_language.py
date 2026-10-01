"""user_profiles.chat_language (ADR 0017)

Revision ID: 7c2e5a91d0b4
Revises: 3b9e61d4c2a7
Create Date: 2026-10-01 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c2e5a91d0b4"
down_revision: str | Sequence[str] | None = "3b9e61d4c2a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("user_profiles", sa.Column("chat_language", sa.String(length=5), nullable=True))
    op.create_check_constraint(
        op.f("ck_user_profiles_chat_language"),
        "user_profiles",
        "chat_language IS NULL OR chat_language IN ('zh', 'en')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_user_profiles_chat_language"), "user_profiles", type_="check")
    op.drop_column("user_profiles", "chat_language")
