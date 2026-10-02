"""exercise_sets.rules_version: replan a set generated ahead of time after a rules change (Q33e)

Revision ID: 9f45cf7f00b8
Revises: 3b9536dae2f6
Create Date: 2026-10-02 15:19:44.567171

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f45cf7f00b8"
down_revision: str | Sequence[str] | None = "3b9536dae2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "exercise_sets",
        sa.Column("rules_version", sa.String(length=50), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("exercise_sets", "rules_version")
