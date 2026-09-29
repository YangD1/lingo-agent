"""Words the learner asked about go on their word list (ADR 0011, task 13)."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity.service import CollectedWord, WordsCollected
from app.db.models import UserCard, Word
from app.memory.reflection import Reflection, VocabCandidate
from app.services.vocab import mine
from tests.integration.test_chat_send import connect, history, login, new_conversation, send
from tests.integration.test_reflection import FakeReflector, idle, learner, reflector  # noqa: F401
from tests.integration.test_reflection_activity import by_name, rows


async def seed(session: AsyncSession) -> dict[str, int]:
    words = [
        Word(word=name, translation=f"{name} 释义", frq=frq, exchange=exchange)
        for name, frq, exchange in [
            ("go", 35, "i:going/p:went/d:gone/3:goes"),
            ("reluctant", 4000, None),
            ("common", 100, None),
        ]
    ]
    session.add_all(words)
    await session.commit()
    return {w.word: w.id for w in words}


def asking(*pairs: tuple[str, str]) -> Reflection:
    return Reflection(vocab_candidates=[VocabCandidate(message=m, word=w) for m, w in pairs])


async def cards(session: AsyncSession, user_id: uuid.UUID) -> dict[int, tuple[str, str]]:
    session.expire_all()
    found = await session.scalars(select(UserCard).where(UserCard.user_id == user_id))
    return {c.word_id: (c.source, c.status) for c in found}


async def activity(client: AsyncClient, conversation_id: str) -> dict[str, Any]:
    response = await client.get(f"/conversations/{conversation_id}/activity")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_asked_words_are_collected_and_shown_under_the_message(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    ids = await seed(db_session)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    user, _ = await learner(db_session)
    user_id = user.id
    # Marked known in a word book: the model may be wrong, so it is left alone.
    db_session.add(UserCard(user_id=user_id, word_id=ids["common"], source="book", status="known"))
    await db_session.commit()
    reflector.reflections.append(
        asking(("u1", "went"), ("u1", "common"), ("u1", "hesitate"), ("u1", "Go"))
    )

    await send(client, conversation_id, "What does went mean? And common? And hesitate?")
    await idle(app)

    assert await cards(db_session, user_id) == {
        ids["go"]: ("auto", "new"),
        ids["common"]: ("book", "known"),
    }
    turn = (await history(client, conversation_id))[0]["id"]
    [row] = by_name(await rows(db_session, user_id, conversation_id), "vocab_collect")
    assert (row.turn_id, row.kind, row.status) == (turn, "background", "ok")
    assert WordsCollected.model_validate(row.summary) == WordsCollected(
        added=[CollectedWord(word_id=ids["go"], word="go")],
        existing=[CollectedWord(word_id=ids["common"], word="common")],
    )
    assert (await activity(client, conversation_id))["words_on_list"] == [ids["go"]]

    # Removing it from the list undoes the step exactly.
    response = await client.delete(f"/vocab/mine/{ids['go']}")
    assert response.status_code == 204
    assert (await activity(client, conversation_id))["words_on_list"] == []
    assert await cards(db_session, user_id) == {ids["common"]: ("book", "known")}


async def test_a_batch_shows_each_word_under_the_first_message_asking(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await seed(db_session)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    app.state.reflection_worker.enabled = False  # the first turn waits for the second
    await send(client, conversation_id, "What does went mean?")
    app.state.reflection_worker.enabled = True
    reflector.reflections.append(asking(("u1", "went"), ("u2", "go"), ("u2", "reluctant")))
    await send(client, conversation_id, "And go? And reluctant?")
    await idle(app)

    user, _ = await learner(db_session)
    first, _, second, _ = [m["id"] for m in await history(client, conversation_id)]
    found = by_name(await rows(db_session, user.id, conversation_id), "vocab_collect")
    assert [(r.turn_id, [w["word"] for w in r.summary["added"]]) for r in found] == [
        (first, ["go"]),
        (second, ["reluctant"]),
    ]


async def test_nothing_is_recorded_when_no_word_was_asked_or_found(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await seed(db_session)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    reflector.reflections.append(asking(("u1", "hesitate")))

    await send(client, conversation_id, "What does hesitate mean?")
    await send(client, conversation_id, "Thanks!")
    await idle(app)

    user, _ = await learner(db_session)
    user_id = user.id
    assert by_name(await rows(db_session, user_id, conversation_id), "vocab_collect") == []
    assert await cards(db_session, user_id) == {}


async def test_a_failure_is_shown_under_the_messages_that_asked(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database gone")

    monkeypatch.setattr(mine, "collect", broken)
    await seed(db_session)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    reflector.reflections.append(asking(("u1", "reluctant")))

    await send(client, conversation_id, "What does reluctant mean?")
    await idle(app)

    user, _ = await learner(db_session)
    user_id = user.id
    found = await rows(db_session, user_id, conversation_id)
    [row] = by_name(found, "vocab_collect")
    assert (row.status, row.summary) == ("failed", {})
    # Memory and grammar were already saved and are unaffected.
    assert {r.status for r in found} == {
        "ok",
        "failed",
    }
