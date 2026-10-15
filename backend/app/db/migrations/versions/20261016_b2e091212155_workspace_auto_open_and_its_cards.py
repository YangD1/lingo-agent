"""workspace auto open and its cards (ADR 0045)

Revision ID: b2e091212155
Revises: 1dae8661b914
Create Date: 2026-10-16 00:13:11.292022

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e091212155"
down_revision: str | Sequence[str] | None = "1dae8661b914"
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
)
NEW = ("workspace_closed", "workspace_auto")


def _listed(names: tuple[str, ...]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def _kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_tutor_cards_kind"), "tutor_cards", type_="check")
    op.create_check_constraint(
        op.f("ck_tutor_cards_kind"), "tutor_cards", f"kind IN ({_listed(kinds)})"
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tutor_profiles",
        sa.Column("workspace_auto_open", sa.Boolean(), server_default="true", nullable=False),
    )
    _kinds((*KINDS, *NEW))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DELETE FROM tutor_cards WHERE kind IN ({_listed(NEW)})")
    _kinds(KINDS)
    op.drop_column("tutor_profiles", "workspace_auto_open")
