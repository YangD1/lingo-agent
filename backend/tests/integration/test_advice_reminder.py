"""What the placement-test reminder reads from the database (task 50)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice.reminder import LastTest, ReminderSignals, current, load
from app.db.models import KCMastery
from tests.integration.test_advice_candidates import placement
from tests.integration.test_dashboard import new_user

RULES = get_rules()
CATALOG = get_grammar_catalog()
NOW = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)
B1 = [kc.id for kc in CATALOG.kcs if kc.cefr == "B1"]
A2 = [kc.id for kc in CATALOG.kcs if kc.cefr == "A2"]


def learned(user_id: object, kc_id: str) -> KCMastery:
    return KCMastery(
        user_id=user_id,
        kc_id=kc_id,
        kind="grammar",
        p_mastery=0.97,
        rules_version=RULES.version,
        mastered_at=NOW - timedelta(days=3),
        due=NOW + timedelta(days=5),
    )


async def test_a_new_learner(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)

    assert await load(db_session, user_id, rules=RULES, catalog=CATALOG) == ReminderSignals(
        None, None
    )
    found = await current(db_session, user_id, rules=RULES, catalog=CATALOG, now=NOW)
    assert found is not None and found.key == "never"


async def test_learned_points_at_the_latest_tests_level(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)
    old = placement(user_id, NOW - timedelta(days=100))
    old.result = {**old.result, "cefr": "A2"}  # type: ignore[dict-item]
    latest = placement(user_id, NOW - timedelta(days=20))  # B1
    db_session.add_all([old, latest])
    # Learned: most of B1, plus A2 points that are not the current level.
    share = RULES.advice.retest_learned_share
    count = int(-(-len(B1) * share // 1))
    db_session.add_all([learned(user_id, kc) for kc in B1[:count] + A2[:5]])
    # Not learned (yet): counts toward nothing.
    db_session.add(
        KCMastery(
            user_id=user_id,
            kc_id=B1[-1],
            kind="grammar",
            p_mastery=0.6,
            rules_version=RULES.version,
        )
    )
    await db_session.flush()

    found = await load(db_session, user_id, rules=RULES, catalog=CATALOG)

    assert found == ReminderSignals(
        None,
        LastTest(latest.id, latest.finished_at, "B1", count, len(B1)),  # type: ignore[arg-type]
    )
    reminder = await current(db_session, user_id, rules=RULES, catalog=CATALOG, now=NOW)
    assert reminder is not None
    assert (reminder.reason, reminder.key) == ("progress", f"progress:{latest.id}")


async def test_an_open_test(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)
    running = placement(user_id, None)
    db_session.add_all([placement(user_id, NOW - timedelta(days=5)), running])
    await db_session.flush()

    found = await current(db_session, user_id, rules=RULES, catalog=CATALOG, now=NOW)

    assert found is not None and found.key == f"resume:{running.id}"
