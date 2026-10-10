"""Evidence from speaking conversations (task 58.4, ADR 0029 §4, Q58a-b)."""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.evidence import ChatEvidence, record_chat_evidence
from app.adaptive.rules import get_rules
from app.db.models import Attachment, Conversation, KCEvidence, KCMastery, SpeakingSession
from app.memory.reflection import Reflection, TaggedMistake
from app.speaking.evidence import evidence_source, kept_evidence, mark_corrected
from tests.integration.test_chat_send import connect, login, send
from tests.integration.test_learner_evidence import KC, setup, wrong
from tests.integration.test_reflection import FakeReflector, idle, reflector  # noqa: F401

RULES = get_rules()


async def speaking_conversation(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user_id, conversation_id = await setup(session, level="A2")
    conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    conversation.purpose = "speaking"
    session.add(SpeakingSession(user_id=user_id, conversation_id=conversation_id, level="A2"))
    await session.flush()
    return user_id, conversation_id


async def spoken(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: str
) -> None:
    conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    session.add(
        Attachment(
            tenant_id=conversation.tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            kind="audio",
            mime_type="audio/webm",
            filename="voice.webm",
            size_bytes=3,
            sha256="0" * 64,
            data=b"abc",
            status="ready",
            text="transcript",
        )
    )
    await session.flush()


def right(message_id: str) -> ChatEvidence:
    return ChatEvidence(message_id=message_id, kc_id=KC, correct=True)


def test_speaking_conversations_record_speaking_evidence() -> None:
    assert evidence_source("speaking") == evidence_source("realtime") == "speaking"
    assert evidence_source(None) == evidence_source("daily") == "chat"


async def test_short_spoken_turns_give_no_mistakes(db_session: AsyncSession) -> None:
    user_id, conversation_id = await speaking_conversation(db_session)
    for message_id in ("short", "long"):
        await spoken(db_session, user_id, conversation_id, message_id)
    texts = {
        "short": "She like.",  # spoken, 2 words
        "long": "She like music a lot.",  # spoken, 5 words
        "typed": "She like.",  # typed: not filtered
    }
    items = [wrong("short"), right("short"), wrong("long"), wrong("typed")]

    kept = await kept_evidence(db_session, conversation_id, items, texts, RULES)

    assert [(i.message_id, i.correct) for i in kept] == [
        ("short", True),
        ("long", False),
        ("typed", False),
    ]


async def test_a_corrected_turn_gives_nothing_and_loses_what_it_gave(
    db_session: AsyncSession,
) -> None:
    user_id, conversation_id = await speaking_conversation(db_session)
    await record_chat_evidence(
        db_session,
        user_id=user_id,
        conversation_id=conversation_id,
        message_ids=["m1", "m2"],
        items=[wrong("m1"), wrong("m2")],
        source="speaking",
    )
    rows = (await db_session.scalars(select(KCEvidence))).all()
    assert {r.source for r in rows} == {"speaking"}

    assert await mark_corrected(db_session, user_id, conversation_id, "m1")
    assert await mark_corrected(db_session, user_id, conversation_id, "m1")  # once is enough

    left = (await db_session.scalars(select(KCEvidence))).all()
    assert [r.message_id for r in left] == ["m2"]
    row = await db_session.scalar(select(SpeakingSession))
    assert row is not None and row.corrected_message_ids == ["m1"]
    mastery = await db_session.get(KCMastery, (user_id, KC))
    assert mastery is not None
    # Reflected again later (a retry), the corrected turn still gives nothing.
    kept = await kept_evidence(
        db_session, conversation_id, [wrong("m1"), right("m2")], {"m1": "", "m2": ""}, RULES
    )
    assert [i.message_id for i in kept] == ["m2"]


async def test_correcting_needs_a_speaking_session(db_session: AsyncSession) -> None:
    user_id, conversation_id = await setup(db_session)
    assert not await mark_corrected(db_session, user_id, conversation_id, "m1")
    other_user, _ = await setup(db_session)
    _, speaking_id = await speaking_conversation(db_session)
    assert not await mark_corrected(db_session, other_user, speaking_id, "m1")


async def test_reflection_records_a_speaking_turn_as_speaking_evidence(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    body = (await client.post("/speaking/sessions", json={"scenario_id": None})).json()
    reflector.reflections.append(
        Reflection(
            mistakes=[
                TaggedMistake(
                    message="u1",
                    kc_id=KC,
                    error_type="omission",
                    severity="high",
                    original="She like",
                    correction="She likes",
                )
            ]
        )
    )

    status, _, _ = await send(client, body["conversation_id"], "She like music.")
    assert status == 200
    await idle(app)

    rows = (await db_session.scalars(select(KCEvidence))).all()
    assert [(r.kc_id, r.source, r.evidence) for r in rows] == [(KC, "speaking", "production")]
