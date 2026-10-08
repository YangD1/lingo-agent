"""Practice priority raised for the KCs a diagnosis names (Q46e, P2 plan §3.3).

A flat `diagnosis.boost` for `boost_days` after the diagnosis, until the KC is learned.
The model's confidence plays no part: numbers come from rules, not from the model.
"""

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import Rules
from app.db.models import Diagnosis


def boost_for(
    diagnoses: Iterable[Sequence[Mapping[str, Any]]], learned: Collection[str], rules: Rules
) -> dict[str, float]:
    """Per KC named by a root cause of these diagnoses and not learned, the factor."""
    named = {kc_id for causes in diagnoses for cause in causes for kc_id in cause["kc_ids"]}
    return {kc_id: rules.diagnosis.boost for kc_id in sorted(named - set(learned))}


async def load_boost(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    learned: Collection[str],
    rules: Rules,
    now: datetime,
) -> dict[str, float]:
    """The boost from the learner's diagnoses of the last `boost_days`."""
    rows: Iterable[list[dict[str, Any]]] = await session.scalars(
        select(Diagnosis.root_causes).where(
            Diagnosis.user_id == user_id,
            Diagnosis.created_at >= now - timedelta(days=rules.diagnosis.boost_days),
        )
    )
    return boost_for(rows, learned, rules)
