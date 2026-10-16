"""tutor card withdrawn

Revision ID: a6d5d0cbe419
Revises: c3a7f05e9d21
Create Date: 2026-10-16 18:47:46.128415

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6d5d0cbe419"
down_revision: str | Sequence[str] | None = "c3a7f05e9d21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("proposed", "applied", "declined", "undone", "info")


def upgrade() -> None:
    op.add_column(
        "tutor_cards", sa.Column("withdrawn_reason", sa.String(length=300), nullable=True)
    )
    _statuses((*_STATUSES, "withdrawn"))


def downgrade() -> None:
    op.execute("UPDATE tutor_cards SET status = 'info' WHERE status = 'withdrawn'")
    _statuses(_STATUSES)
    op.drop_column("tutor_cards", "withdrawn_reason")


def _statuses(names: tuple[str, ...]) -> None:
    """The tutor may withdraw a card it showed by mistake (ADR 0049)."""
    op.drop_constraint(op.f("ck_tutor_cards_status"), "tutor_cards", type_="check")
    listed = ", ".join(f"'{n}'" for n in names)
    op.create_check_constraint(
        op.f("ck_tutor_cards_status"), "tutor_cards", f"status IN ({listed})"
    )
