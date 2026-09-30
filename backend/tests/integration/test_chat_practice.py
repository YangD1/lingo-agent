import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.adaptive import mastery
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.chat.practice import DatabasePractice, Mistake
from app.chat.turn import OPENING_TURN_ID, OPENING_USAGE_TASK
from app.db.models import KCEvidence
from app.db.session import create_sessionmaker
from app.usage import recorder as usage_recorder
from app.usage.recorder import UsageRecord
from tests.integration.test_chat_send import (
    REPLY,
    connect,
    fake_models,
    login,
    parse_sse,
)
from tests.integration.test_dashboard import new_user

KC = "g.word_order_svo"
NOW = datetime.now(UTC)


def mistake(
    user_id: uuid.UUID, original: str, *, days_ago: int, kc_id: str = KC, source: str = "chat"
) -> KCEvidence:
    return KCEvidence(
        user_id=user_id,
        kc_id=kc_id,
        correct=False,
        evidence="production" if source == "chat" else "recognition",
        source=source,
        error_type="word_order",
        severity="medium",
        original=original,
        correction=f"fixed: {original}",
        created_at=NOW - timedelta(days=days_ago),
    )


async def test_reads_mastery_state_and_the_latest_chat_mistakes(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    user_id, _ = await new_user(db_session)
    other_id, _ = await new_user(db_session)
    db_session.add_all(
        [
            mistake(user_id, "oldest", days_ago=90),
            mistake(user_id, "older", days_ago=3),
            mistake(user_id, "newest", days_ago=1),
            mistake(user_id, "a test answer", days_ago=0, source="placement"),
            mistake(user_id, "another point", days_ago=0, kc_id="g.be_present"),
            mistake(other_id, "someone else", days_ago=0),
        ]
    )
    await db_session.flush()
    await mastery.refresh(
        db_session, user_id, [KC], rules=get_rules(), catalog=get_grammar_catalog()
    )
    await db_session.commit()

    focus = await DatabasePractice(create_sessionmaker(db_engine), user_id, KC).load()

    assert focus is not None and focus.kc.id == KC
    assert focus.state == "weak"
    assert focus.mistakes == [Mistake("newest", "fixed: newest"), Mistake("older", "fixed: older")]


async def test_a_point_without_evidence_or_in_no_catalog(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    user_id, _ = await new_user(db_session)
    await db_session.commit()
    sessionmaker = create_sessionmaker(db_engine)

    focus = await DatabasePractice(sessionmaker, user_id, KC).load()

    assert focus is not None and (focus.state, focus.mistakes) == (None, [])
    assert await DatabasePractice(sessionmaker, user_id, "g.retired").load() is None


@pytest.mark.parametrize("focus_kc_id", [KC, None])
async def test_the_turn_reports_which_point_it_practises(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, focus_kc_id: str | None
) -> None:
    fake_models(monkeypatch)
    await login(client)
    await connect(client, "deepseek")
    created = await client.post("/conversations", json={"focus_kc_id": focus_kc_id})
    conversation_id = created.json()["id"]

    response = await client.post(
        f"/conversations/{conversation_id}/messages", json={"content": "I school go."}
    )

    [load] = [d for kind, d in parse_sse(response.text) if kind == "activity"][:1]
    assert load["name"] == "load_context"
    assert load["summary"]["practice_kc"] == focus_kc_id


@pytest.fixture
def usage_records() -> Iterator[list[UsageRecord]]:
    records: list[UsageRecord] = []
    usage_recorder.set_usage_sink(records.append)
    yield records
    usage_recorder.set_usage_sink(None)


async def open_practice(client: AsyncClient, conversation_id: str) -> Response:
    return await client.post(f"/conversations/{conversation_id}/opening")


async def new_practice(client: AsyncClient) -> str:
    response = await client.post("/conversations", json={"focus_kc_id": KC})
    conversation_id: str = response.json()["id"]
    return conversation_id


async def test_the_tutor_opens_a_practice_conversation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, usage_records: list[UsageRecord]
) -> None:
    fake_models(monkeypatch)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_practice(client)

    response = await open_practice(client, conversation_id)

    assert response.status_code == 200
    events = parse_sse(response.text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "activity" and kinds[-1] == "done"
    assert "".join(d["text"] for kind, d in events if kind == "token") == REPLY
    activity, done = events[0][1], events[-1][1]
    assert activity["turn_id"] == done["turn_id"] == OPENING_TURN_ID
    assert activity["summary"]["practice_kc"] == KC
    # Only the tutor's message is kept: nothing was said on the learner's behalf.
    history = (await client.get(f"/conversations/{conversation_id}/messages")).json()
    assert [(m["role"], m["content"]) for m in history] == [("assistant", REPLY)]
    # Served by the chat model, but not counted as a chat turn of the learner's.
    [record] = usage_records
    assert (record.task, record.connection_name) == (OPENING_USAGE_TASK, "deepseek")

    # It opens once; after that, and after the learner speaks, it's a conflict.
    again = await open_practice(client, conversation_id)
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "conversation_started")
    assert len((await client.get(f"/conversations/{conversation_id}/messages")).json()) == 1


async def test_only_an_unstarted_practice_conversation_opens(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_models(monkeypatch)
    await login(client)
    practice = await new_practice(client)
    free = (await client.post("/conversations")).json()["id"]

    # No chat model yet: refused before anything is stored.
    response = await open_practice(client, practice)
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "no_llm_configured")

    await connect(client, "deepseek")
    response = await open_practice(client, free)
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "not_practice")

    await client.post(f"/conversations/{practice}/messages", json={"content": "Hi!"})
    response = await open_practice(client, practice)
    assert response.json()["detail"]["code"] == "conversation_started"

    await login(client, "mallory@example.com")
    assert (await open_practice(client, practice)).status_code == 404
