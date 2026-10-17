"""lesson cards (ADR 0054 §1)

Revision ID: 8d4ebcf8f132
Revises: 3cf6bc990e25
Create Date: 2026-10-17 18:06:47.076313

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d4ebcf8f132"
down_revision: str | Sequence[str] | None = "3cf6bc990e25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


KINDS = (
    "word_book",
    "learning_goal",
    "practice",
    "link",
    "writing",
    "daily_plan",
    "workspace",
    "workspace_edit",
    "quiz",
    "workspace_closed",
    "workspace_auto",
)
NEW = ("lesson",)


def _listed(names: tuple[str, ...]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def _kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_tutor_cards_kind"), "tutor_cards", type_="check")
    op.create_check_constraint(
        op.f("ck_tutor_cards_kind"), "tutor_cards", f"kind IN ({_listed(kinds)})"
    )


def upgrade() -> None:
    """Upgrade schema."""
    _kinds((*KINDS, *NEW))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DELETE FROM tutor_cards WHERE kind IN ({_listed(NEW)})")
    _kinds(KINDS)
