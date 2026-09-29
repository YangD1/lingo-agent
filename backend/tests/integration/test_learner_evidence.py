"""Evidence → kc_mastery (ADR 0012 §2), and the full path from a chat message."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.bkt import Observation, prior, replay
from app.adaptive.evidence import ChatEvidence, record_chat_evidence
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.db.models import Conversation, KCEvidence, KCMastery, Tenant, User, UserProfile
from app.memory.reflection import Reflection, TaggedMistake, UsedCorrectly
from tests.integration.test_chat_send import connect, login, new_conversation, send
from tests.integration.test_reflection import FakeReflector, idle, learner, reflector  # noqa: F401

KC = "g.present_simple_third_person"  # A1
CATALOG, RULES = get_grammar_catalog(), get_rules()


async def setup(session: AsyncSession, level: str | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = Tenant(name="personal", kind="personal")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    conversation = Conversation(tenant_id=tenant.id, user_id=user.id)
    session.add(conversation)
    if level:
        session.add(UserProfile(user_id=user.id, cefr_level=level))
    await session.flush()
    return user.id, conversation.id


def wrong(message_id: str, kc_id: str = KC) -> ChatEvidence:
    return ChatEvidence(
        message_id=message_id,
        kc_id=kc_id,
        correct=False,
        error_type="omission",
        severity="medium",
        original="She like",
        correction="She likes",
    )


async def test_recording_the_same_messages_again_replaces_their_evidence(
    db_session: AsyncSession,
) -> None:
    user_id, conversation_id = await setup(db_session)
    first = [wrong("m1"), wrong("m1", "g.articles_basic")]
    affected = await record_chat_evidence(
        db_session,
        user_id=user_id,
        conversation_id=conversation_id,
        message_ids=["m1"],
        items=first,
    )
    assert affected == {KC, "g.articles_basic"}
    # A retry that now finds only one error: the article row goes, and is reported.
    affected = await record_chat_evidence(
        db_session,
        user_id=user_id,
        conversation_id=conversation_id,
        message_ids=["m1"],
        items=[wrong("m1")],
    )
    assert affected == {KC, "g.articles_basic"}
    rows = (await db_session.scalars(select(KCEvidence))).all()
    assert [(r.message_id, r.kc_id) for r in rows] == [("m1", KC)]


async def test_refresh_replays_evidence_with_the_learners_prior(db_session: AsyncSession) -> None:
    user_id, conversation_id = await setup(db_session, level="B1")
    await record_chat_evidence(
        db_session,
        user_id=user_id,
        conversation_id=conversation_id,
        message_ids=["m1", "m2"],
        items=[wrong("m1"), ChatEvidence(message_id="m2", kc_id=KC, correct=True)],
    )
    await mastery.refresh(db_session, user_id, [KC, "w.apple"], rules=RULES, catalog=CATALOG)

    row = await db_session.get(KCMastery, (user_id, KC))
    assert row is not None and row.kind == "grammar" and row.rules_version == RULES.version
    rows = (await db_session.scalars(select(KCEvidence).order_by(KCEvidence.id))).all()
    want = replay(
        [
            Observation(r.correct, "production", r.created_at, r.message_id, r.severity)
            for r in rows
        ],  # type: ignore[arg-type]
        prior("A1", "B1", RULES),
        RULES,
    )
    assert row.p_mastery == pytest.approx(want.p_mastery)
    assert (row.observations, row.produce_correct) == (2, 1)
    assert await db_session.get(KCMastery, (user_id, "w.apple")) is None  # words: FSRS

    # All of the KC's evidence gone (the learner deleted it): so is the row.
    await record_chat_evidence(
        db_session,
        user_id=user_id,
        conversation_id=conversation_id,
        message_ids=["m1", "m2"],
        items=[],
    )
    await mastery.refresh(db_session, user_id, [KC], rules=RULES, catalog=CATALOG)
    assert await db_session.get(KCMastery, (user_id, KC)) is None


async def test_rows_from_other_rules_are_rebuilt(db_session: AsyncSession) -> None:
    user_id, conversation_id = await setup(db_session)
    await record_chat_evidence(
        db_session,
        user_id=user_id,
        conversation_id=conversation_id,
        message_ids=["m1"],
        items=[wrong("m1")],
    )
    await mastery.refresh(db_session, user_id, [KC], rules=RULES, catalog=CATALOG)
    assert not await mastery.ensure_current(db_session, user_id, rules=RULES, catalog=CATALOG)

    await db_session.execute(
        update(KCMastery)
        .values(rules_version="old", p_mastery=0.5)
        .where(KCMastery.user_id == user_id)
    )
    assert await mastery.ensure_current(db_session, user_id, rules=RULES, catalog=CATALOG)
    db_session.expire_all()
    row = await db_session.get(KCMastery, (user_id, KC))
    assert row is not None and row.rules_version == RULES.version and row.p_mastery != 0.5


async def test_chat_mistakes_reach_the_learner_model(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    reflector: FakeReflector,  # noqa: F811
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
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
                    l1_transfer=True,
                ),
                TaggedMistake(
                    message="u1",
                    kc_id="g.not_a_kc",
                    error_type="omission",
                    severity="high",
                    original="x",
                    correction="y",
                ),
            ],
            used_correctly=[UsedCorrectly(message="u1", kc_id="g.present_continuous")],
        )
    )
    user, _ = await learner(db_session)

    status, _, _ = await send(client, conversation_id, "She like music and she is playing now.")
    assert status == 200
    await idle(app)

    rows = (await db_session.scalars(select(KCEvidence).order_by(KCEvidence.id))).all()
    assert [(r.kc_id, r.correct, r.severity) for r in rows] == [
        (KC, False, "high"),
        ("g.present_continuous", True, None),
    ]
    assert rows[0].conversation_id == uuid.UUID(conversation_id) and rows[0].l1_transfer
    assert rows[0].message_id is not None and rows[0].message_id == rows[1].message_id
    kcs = await db_session.scalars(select(KCMastery.kc_id).where(KCMastery.user_id == user.id))
    assert set(kcs) == {KC, "g.present_continuous"}
    [prompt] = reflector.prompts
    assert "Learner [u1]: She like music" in prompt
