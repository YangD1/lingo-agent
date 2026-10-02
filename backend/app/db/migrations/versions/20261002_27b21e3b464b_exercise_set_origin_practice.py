"""exercise set origin practice

Revision ID: 27b21e3b464b
Revises: f6717e7b015f
Create Date: 2026-10-02 17:01:09.795505

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "27b21e3b464b"
down_revision: str | Sequence[str] | None = "f6717e7b015f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _origins(("dashboard", "learner", "card", "plan", "practice", "prefetch"))


def downgrade() -> None:
    op.execute("UPDATE exercise_sets SET origin = 'dashboard' WHERE origin = 'practice'")
    _origins(("dashboard", "learner", "card", "plan", "prefetch"))


def _origins(names: tuple[str, ...]) -> None:
    """Sets started from the practice page itself (task 35) get their own origin."""
    op.drop_constraint(op.f("ck_exercise_sets_origin"), "exercise_sets", type_="check")
    listed = ", ".join(f"'{n}'" for n in names)
    op.create_check_constraint(
        op.f("ck_exercise_sets_origin"), "exercise_sets", f"origin IN ({listed})"
    )
