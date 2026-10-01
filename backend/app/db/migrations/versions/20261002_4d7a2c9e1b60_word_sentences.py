"""word_sentences (ADR 0020)

Revision ID: 4d7a2c9e1b60
Revises: 6a0fc12e79ca
Create Date: 2026-10-02 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4d7a2c9e1b60"
down_revision: str | Sequence[str] | None = "6a0fc12e79ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "word_sentences",
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("en", sa.Text(), nullable=False),
        sa.Column("zh", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["word_id"], ["words.id"], name=op.f("fk_word_sentences_word_id_words")
        ),
        sa.PrimaryKeyConstraint("word_id", "source", "rank", name=op.f("pk_word_sentences")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("word_sentences")
