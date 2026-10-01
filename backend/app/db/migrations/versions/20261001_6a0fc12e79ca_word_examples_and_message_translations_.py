"""word examples and message translations (ADR 0017)

Revision ID: 6a0fc12e79ca
Revises: 7c2e5a91d0b4
Create Date: 2026-10-01 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6a0fc12e79ca"
down_revision: str | Sequence[str] | None = "7c2e5a91d0b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "word_examples",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("cefr", sa.String(length=2), nullable=False),
        sa.Column("sentences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cefr IN ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')", name=op.f("ck_word_examples_cefr")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_word_examples_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["word_id"], ["words.id"], name=op.f("fk_word_examples_word_id_words")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "word_id", "cefr", name=op.f("pk_word_examples")),
    )
    op.create_table(
        "message_translations",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.String(length=100), nullable=False),
        sa.Column("target", sa.String(length=5), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("target IN ('zh', 'en')", name=op.f("ck_message_translations_target")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_message_translations_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id", "message_id", "target", name=op.f("pk_message_translations")
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("message_translations")
    op.drop_table("word_examples")
