"""word_senses; word_sentences.zh nullable (ADR 0062)

Revision ID: 8c3e5f1a2d47
Revises: 6915c7a4b30e
Create Date: 2026-10-21 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8c3e5f1a2d47"
down_revision: str | Sequence[str] | None = "6915c7a4b30e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "word_senses",
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("pos", sa.String(length=20), nullable=False),
        sa.Column("gloss", sa.Text(), nullable=False),
        sa.Column(
            "labels", postgresql.ARRAY(sa.String(length=40)), server_default="{}", nullable=False
        ),
        sa.Column("examples", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "synonyms", postgresql.ARRAY(sa.String(length=100)), server_default="{}", nullable=False
        ),
        sa.Column(
            "antonyms", postgresql.ARRAY(sa.String(length=100)), server_default="{}", nullable=False
        ),
        sa.Column("source_title", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["word_id"], ["words.id"], name=op.f("fk_word_senses_word_id_words")
        ),
        sa.PrimaryKeyConstraint("word_id", "source", "rank", name=op.f("pk_word_senses")),
    )
    op.alter_column("word_sentences", "zh", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM word_sentences WHERE zh IS NULL")
    op.alter_column("word_sentences", "zh", existing_type=sa.Text(), nullable=False)
    op.drop_table("word_senses")
