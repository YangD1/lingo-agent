import uuid
from functools import partial

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity import service
from app.activity.service import ContextRead, GrammarMistake, GrammarTags, MemoryChanges
from app.db.models import AgentActivity, Conversation, Tenant, User


async def _conversation(session: AsyncSession) -> Conversation:
    tenant = Tenant(name="personal", kind="personal")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    conversation = Conversation(tenant_id=tenant.id, user_id=user.id)
    session.add(conversation)
    await session.flush()
    return conversation


async def test_rewriting_a_step_replaces_it(db_session: AsyncSession) -> None:
    c = await _conversation(db_session)
    record = partial(
        service.record, db_session, user_id=c.user_id, conversation_id=c.id, turn_id="t1"
    )
    mistake = GrammarMistake(
        kc_id="g.present_simple_third_person",
        error_type="omission",
        severity="medium",
        original="she like it",
        correction="she likes it",
    )
    await record(name="grammar_tagging", summary=GrammarTags())
    await record(name="grammar_tagging", summary=GrammarTags(mistakes=[mistake]))
    await record(name="load_context", summary=ContextRead())

    rows = await service.list_activities(db_session, c.user_id, c.id)
    assert [(r.name, r.kind) for r in rows] == [
        ("grammar_tagging", "background"),
        ("load_context", "step"),
    ]
    tags = service.parse_summary(rows[0])
    assert isinstance(tags, GrammarTags) and tags.mistakes == [mistake]


async def test_failed_step_keeps_no_summary(db_session: AsyncSession) -> None:
    c = await _conversation(db_session)
    await service.record(
        db_session,
        user_id=c.user_id,
        conversation_id=c.id,
        turn_id="t1",
        name="reflect_memory",
        status="failed",
        summary=MemoryChanges(deleted=2),
        duration_ms=12,
    )
    [row] = await service.list_activities(db_session, c.user_id, c.id)
    assert (row.status, row.summary, row.duration_ms) == ("failed", {}, 12)


async def test_summary_must_match_the_step(db_session: AsyncSession) -> None:
    c = await _conversation(db_session)
    with pytest.raises(TypeError):
        await service.record(
            db_session,
            user_id=c.user_id,
            conversation_id=c.id,
            turn_id="t1",
            name="load_context",
            summary=MemoryChanges(),
        )


async def test_filters_by_turn_and_owner(db_session: AsyncSession) -> None:
    c = await _conversation(db_session)
    for turn in ("t1", "t2"):
        await service.record(
            db_session, user_id=c.user_id, conversation_id=c.id, turn_id=turn, name="load_context"
        )
    rows = await service.list_activities(db_session, c.user_id, c.id, turn_ids=["t2"])
    assert [r.turn_id for r in rows] == ["t2"]
    assert await service.list_activities(db_session, uuid.uuid4(), c.id) == []


async def test_status_check(db_session: AsyncSession) -> None:
    c = await _conversation(db_session)
    db_session.add(
        AgentActivity(
            user_id=c.user_id,
            conversation_id=c.id,
            turn_id="t1",
            kind="step",
            name="load_context",
            status="maybe",
        )
    )
    with pytest.raises(IntegrityError, match="ck_agent_activities_status"):
        await db_session.flush()


async def test_deleted_with_the_conversation(db_session: AsyncSession) -> None:
    c = await _conversation(db_session)
    await service.record(
        db_session, user_id=c.user_id, conversation_id=c.id, turn_id="t1", name="load_context"
    )
    await db_session.execute(delete(Conversation).where(Conversation.id == c.id))
    assert await db_session.scalar(select(func.count()).select_from(AgentActivity)) == 0


def test_timed_measures_even_on_error() -> None:
    with pytest.raises(RuntimeError), service.timed() as t:
        raise RuntimeError
    assert t.ms is not None and t.ms >= 0
