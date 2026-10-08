"""Grammar graph queries over `kc_edges` with the learner's data (task 45.4, ADR 0022 §3)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import graph, mastery
from app.adaptive.graph_sync import sync_kc_edges
from app.adaptive.kc.catalog import GrammarCatalog
from app.adaptive.rules import get_rules
from app.db.models import KCEvidence, User, UserProfile

RULES = get_rules()  # prerequisite_depth 3, mistakes_per_kc 3
T0 = datetime(2026, 10, 1, 9, tzinfo=UTC)


def _kc(kc_id: str, cefr: str, **fields: Any) -> dict[str, Any]:
    base = {"id": kc_id, "name_en": kc_id, "name_zh": kc_id, "cefr": cefr}
    return base | {"description": f"Uses {kc_id}."} | fields


# g.d needs g.b and g.c, which both need g.a (a diamond), which needs g.z, which needs
# g.y: four steps from g.d, one past the depth limit. g.d is confusable with g.e, and
# with g.a, which is also in its chain.
CATALOG = GrammarCatalog.model_validate(
    {
        "kcs": [
            _kc("g.y", "A1"),
            _kc("g.z", "A1", prerequisites=["g.y"]),
            _kc("g.a", "A1", prerequisites=["g.z"], confusable_with=["g.d"]),
            _kc("g.b", "A2", prerequisites=["g.a"]),
            _kc("g.c", "A2", prerequisites=["g.a"]),
            _kc("g.d", "B1", prerequisites=["g.b", "g.c"], confusable_with=["g.e"]),
            _kc("g.e", "B1"),
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


def _evidence(user_id: uuid.UUID, kc_id: str, hours: int, *, correct: bool = False) -> KCEvidence:
    return KCEvidence(
        user_id=user_id,
        kc_id=kc_id,
        correct=correct,
        evidence="production",
        source="chat",
        error_type=None if correct else "wrong_form",
        severity=None if correct else "medium",
        original=None if correct else f"wrong {kc_id} {hours}",
        correction=None if correct else f"right {kc_id} {hours}",
        created_at=T0 + timedelta(hours=hours),
    )


async def test_prerequisite_chain_stops_at_depth_and_keeps_shortest_path(
    db_session: AsyncSession,
) -> None:
    await sync_kc_edges(db_session, CATALOG)
    assert await graph.prerequisite_chain(db_session, "g.d", 3) == [
        ("g.b", 1),
        ("g.c", 1),
        ("g.a", 2),
        ("g.z", 3),
    ]
    assert await graph.prerequisite_chain(db_session, "g.d", 1) == [("g.b", 1), ("g.c", 1)]
    assert await graph.prerequisite_chain(db_session, "g.y", 3) == []
    assert await graph.confusables(db_session, "g.d") == ["g.a", "g.e"]
    assert await graph.confusables(db_session, "g.e") == ["g.d"]


async def test_neighborhood_joins_the_learners_mastery_and_latest_mistakes(
    db_session: AsyncSession,
) -> None:
    await sync_kc_edges(db_session, CATALOG)
    me, other = await _learner(db_session), await _learner(db_session)
    db_session.add_all(
        [
            *(_evidence(me, "g.d", hours) for hours in range(4)),
            _evidence(me, "g.a", 0),
            _evidence(me, "g.b", 0, correct=True),
            _evidence(other, "g.e", 9),
        ]
    )
    await db_session.flush()
    await mastery.refresh(db_session, me, ["g.d", "g.a", "g.b"], rules=RULES, catalog=CATALOG)

    found = await graph.neighborhood(db_session, me, "g.d", rules=RULES, catalog=CATALOG)

    assert found is not None
    target = found.target
    assert (target.relation, target.depth, target.required_by) == ("target", 0, ())
    # Only mistakes, newest first, capped.
    assert [m.original for m in target.mistakes] == ["wrong g.d 3", "wrong g.d 2", "wrong g.d 1"]
    assert target.mastery is not None and target.state is not None

    chain = {n.kc.id: n for n in found.prerequisites}
    assert list(chain) == ["g.b", "g.c", "g.a", "g.z"]
    assert chain["g.a"].required_by == ("g.b", "g.c")
    assert chain["g.z"].required_by == ("g.a",)
    assert chain["g.b"].mastery is not None and chain["g.b"].mistakes == ()
    assert [m.correction for m in chain["g.a"].mistakes] == ["right g.a 0"]
    # No evidence yet: still listed, without mastery.
    assert chain["g.c"].mastery is None and chain["g.c"].state is None

    # g.a is in the chain, so it is not repeated as a confusable; another learner's
    # mistakes on g.e are not mine.
    assert [(n.kc.id, n.relation, n.mistakes) for n in found.confusables] == [
        ("g.e", "confusable", ())
    ]


async def test_neighborhood_of_an_unknown_kc(db_session: AsyncSession) -> None:
    me = await _learner(db_session)
    assert await graph.neighborhood(db_session, me, "g.nope", rules=RULES, catalog=CATALOG) is None
