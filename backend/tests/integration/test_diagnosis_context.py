"""What a diagnosis looks at, read from the database (task 46.2, Q46a)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.diagnosis.context import load_context
from app.adaptive.graph_sync import sync_kc_edges
from app.adaptive.kc.catalog import GrammarCatalog
from app.adaptive.rules import get_rules
from app.db.models import KCEvidence, User, UserProfile

RULES = get_rules()  # diagnosis: min_mistakes 3 in mistake_days 30, max_kcs 3
NOW = datetime(2026, 10, 8, 9, tzinfo=UTC)


def _kc(kc_id: str, **fields: Any) -> dict[str, Any]:
    base = {"id": kc_id, "name_en": kc_id, "name_zh": kc_id, "cefr": "B1"}
    return base | {"description": f"Uses {kc_id}."} | fields


CATALOG = GrammarCatalog.model_validate(
    {
        "kcs": [
            _kc("g.base", cefr="A2"),
            _kc("g.one", prerequisites=["g.base"]),
            _kc("g.two"),
            _kc("g.old"),
            _kc("g.test"),
            _kc("g.slips"),
        ]
    }
)


async def _learner(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    session.add(UserProfile(user_id=user.id, cefr_level="B1"))
    await session.flush()
    return user.id


def _mistakes(
    user_id: uuid.UUID,
    kc_id: str,
    count: int,
    *,
    days_ago: float = 1,
    source: str = "chat",
    severity: str = "medium",
) -> list[KCEvidence]:
    return [
        KCEvidence(
            user_id=user_id,
            kc_id=kc_id,
            correct=False,
            evidence="production",
            source=source,
            error_type="wrong_form",
            severity=severity,
            original=f"wrong {kc_id} {n}",
            correction=f"right {kc_id} {n}",
            created_at=NOW - timedelta(days=days_ago, minutes=n),
        )
        for n in range(count)
    ]


async def test_targets_are_kcs_with_enough_counted_mistakes_lately(
    db_session: AsyncSession,
) -> None:
    await sync_kc_edges(db_session, CATALOG)
    me = await _learner(db_session)
    db_session.add_all(
        [
            *_mistakes(me, "g.one", 3),
            *_mistakes(me, "g.two", 5),
            # Too long ago, a test rather than use, minor slips: none count.
            *_mistakes(me, "g.old", 5, days_ago=31),
            *_mistakes(me, "g.test", 5, source="placement"),
            *_mistakes(me, "g.slips", 5, severity="low"),
            *_mistakes(me, "g.base", 1),
        ]
    )
    await db_session.flush()

    context = await load_context(db_session, me, rules=RULES, catalog=CATALOG, now=NOW)

    assert context is not None
    assert sorted(context.targets) == ["g.one", "g.two"]
    one = next(n for n in context.neighborhoods if n.target.kc.id == "g.one")
    assert [n.kc.id for n in one.prerequisites] == ["g.base"]
    # The prerequisite's mistake is shown too, so a cause there can cite it.
    assert set(context.evidence.values()) == {"g.one", "g.two", "g.base"}


async def test_no_context_without_a_qualifying_kc(db_session: AsyncSession) -> None:
    await sync_kc_edges(db_session, CATALOG)
    me = await _learner(db_session)
    db_session.add_all(_mistakes(me, "g.one", 2))
    await db_session.flush()
    assert await load_context(db_session, me, rules=RULES, catalog=CATALOG, now=NOW) is None
