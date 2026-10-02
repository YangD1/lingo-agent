"""writing cards

Revision ID: 5e1a7c3d9b20
Revises: b13e7f785be1
Create Date: 2026-10-03 00:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e1a7c3d9b20"
down_revision: str | Sequence[str] | None = "b13e7f785be1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _kinds(names: tuple[str, ...]) -> None:
    """writing_coach links its review with a card of its own kind (task 38.5)."""
    op.drop_constraint(op.f("ck_tutor_cards_kind"), "tutor_cards", type_="check")
    listed = ", ".join(f"'{n}'" for n in names)
    op.create_check_constraint(op.f("ck_tutor_cards_kind"), "tutor_cards", f"kind IN ({listed})")


def upgrade() -> None:
    """Upgrade schema."""
    _kinds(("word_book", "learning_goal", "practice", "link", "writing"))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM tutor_cards WHERE kind = 'writing'")
    _kinds(("word_book", "learning_goal", "practice", "link"))
