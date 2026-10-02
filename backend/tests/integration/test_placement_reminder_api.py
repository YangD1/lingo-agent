"""Placement-test reminder API (task 50): read it, "Not now", and when it comes back."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import get_rules
from app.db.models import ReminderDismissal, User
from tests.integration.test_advice_candidates import placement
from tests.integration.test_chat_send import login

RULES = get_rules()


async def test_not_now_and_back_again(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    user_id = await db_session.scalar(select(User.id))
    assert user_id is not None

    assert (await client.get("/placement/reminder")).json() == {
        "reason": "never",
        "key": "never",
        "days_since": None,
        "level": None,
        "learned": None,
        "total": None,
        "snoozed": False,
    }

    stale = await client.post("/placement/reminder/dismiss", json={"key": "age:x"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "reminder_changed"
    assert (await db_session.scalars(select(ReminderDismissal))).all() == []

    assert (
        await client.post("/placement/reminder/dismiss", json={"key": "never"})
    ).status_code == 204
    assert (await client.get("/placement/reminder")).json()["snoozed"] is True
    # Saying it again only moves the time.
    assert (
        await client.post("/placement/reminder/dismiss", json={"key": "never"})
    ).status_code == 204

    days = RULES.advice.reminder_snooze_days
    await db_session.execute(
        update(ReminderDismissal).values(dismissed_at=datetime.now(UTC) - timedelta(days=days))
    )
    await db_session.commit()
    assert (await client.get("/placement/reminder")).json()["snoozed"] is False


async def test_a_new_reason_reminds_again(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    user_id = await db_session.scalar(select(User.id))
    assert user_id is not None
    await client.post("/placement/reminder/dismiss", json={"key": "never"})

    test = placement(user_id, datetime.now(UTC) - timedelta(days=RULES.advice.retest_days))
    db_session.add(test)
    await db_session.commit()

    found = (await client.get("/placement/reminder")).json()
    assert found["reason"] == "age" and found["key"] == f"age:{test.id}"
    assert found["level"] == "B1" and found["days_since"] == RULES.advice.retest_days
    assert found["snoozed"] is False


async def test_nothing_after_a_recent_test(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    user_id = await db_session.scalar(select(User.id))
    assert user_id is not None
    db_session.add(placement(user_id, datetime.now(UTC) - timedelta(days=1)))
    await db_session.commit()

    assert (await client.get("/placement/reminder")).json() is None
    gone = await client.post("/placement/reminder/dismiss", json={"key": "never"})
    assert gone.status_code == 409
