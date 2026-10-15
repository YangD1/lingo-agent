"""quiz cards and understanding-check formats (ADR 0044 §3-§4)

Revision ID: 1dae8661b914
Revises: 0b431a2c2832
Create Date: 2026-10-15 20:59:09.378153

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1dae8661b914"
down_revision: str | Sequence[str] | None = "0b431a2c2832"
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
)
FORMATS = ("choice4", "cloze", "find_fix", "transform", "translate", "rewrite_own")
CHECKS = ("concept_choice", "explain")


def _listed(names: tuple[str, ...]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def _constraints(kinds: tuple[str, ...], formats: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_tutor_cards_kind"), "tutor_cards", type_="check")
    op.create_check_constraint(
        op.f("ck_tutor_cards_kind"), "tutor_cards", f"kind IN ({_listed(kinds)})"
    )
    op.drop_constraint(op.f("ck_exercises_format"), "exercises", type_="check")
    op.create_check_constraint(
        op.f("ck_exercises_format"), "exercises", f"format IN ({_listed(formats)})"
    )
    op.drop_constraint(op.f("ck_kc_evidence_format"), "kc_evidence", type_="check")
    op.create_check_constraint(
        op.f("ck_kc_evidence_format"),
        "kc_evidence",
        f"format IS NULL OR format IN ({_listed(formats)})",
    )


def upgrade() -> None:
    """Upgrade schema."""
    _constraints((*KINDS, "quiz"), (*FORMATS, *CHECKS))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM tutor_cards WHERE kind = 'quiz'")
    op.execute(f"DELETE FROM exercises WHERE format IN ({_listed(CHECKS)})")
    _constraints(KINDS, FORMATS)
