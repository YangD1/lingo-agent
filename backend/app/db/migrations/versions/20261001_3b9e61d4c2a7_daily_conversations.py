"""daily conversations; drop learning_advice (ADR 0016)

Revision ID: 3b9e61d4c2a7
Revises: a5025a738252
Create Date: 2026-10-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3b9e61d4c2a7"
down_revision: str | Sequence[str] | None = "a5025a738252"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f("ck_conversations_purpose"), "conversations", type_="check")
    op.create_check_constraint(
        op.f("ck_conversations_purpose"), "conversations", "purpose IN ('planning', 'daily')"
    )
    # The dashboard's advice is a conversation now; its cache goes.
    op.drop_table("learning_advice")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "learning_advice",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("candidate_ids", postgresql.ARRAY(sa.String(length=120)), nullable=False),
        sa.Column("locale", sa.String(length=5), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_by_hand_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("locale IN ('en', 'zh-CN')", name=op.f("ck_learning_advice_locale")),
        sa.CheckConstraint(
            "status IN ('ai', 'no_model', 'failed', 'empty')",
            name=op.f("ck_learning_advice_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_learning_advice_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_learning_advice")),
    )
    op.execute("DELETE FROM conversations WHERE purpose = 'daily'")
    op.drop_constraint(op.f("ck_conversations_purpose"), "conversations", type_="check")
    op.create_check_constraint(
        op.f("ck_conversations_purpose"), "conversations", "purpose IN ('planning')"
    )
