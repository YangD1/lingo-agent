"""What the tutor is told when a realtime call opens (ADR 0030 §3, Q60e)."""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.speaking import FREE_OPENING
from app.db.models import TenantMember, User
from app.memory import service
from app.realtime.context import call_instructions
from app.speaking.scenarios import get_scenarios


async def learner(client: AsyncClient, db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    response = await client.post(
        "/auth/register", json={"email": "talker@example.com", "password": "password123"}
    )
    assert response.status_code == 201
    user = await db_session.scalar(select(User))
    tenant_id = await db_session.scalar(select(TenantMember.tenant_id))
    assert user is not None and tenant_id is not None
    return user.id, tenant_id


async def test_a_scenario_call_knows_the_learner_and_the_scene(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user_id, tenant_id = await learner(client, db_session)
    await service.update_profile(
        db_session, user_id, {"cefr_level": "B1", "occupation": "nurse"}, by_learner=True
    )
    for kind, content in (
        ("fact", "Has a job interview next month"),
        ("episode", "Practised describing their hospital ward"),
    ):
        await service.add_memory(
            db_session, tenant_id=tenant_id, user_id=user_id, kind=kind, content=content
        )
    interview = get_scenarios().get("job_interview")
    assert interview is not None

    text = await call_instructions(app.state.sessionmaker, user_id, interview, None)

    assert "live voice call" in text and "recast" in text
    assert interview.opening in text and interview.role in text
    assert "The learner's level: B1. At most 3 sentences per reply." in text
    assert "Occupation: nurse" in text
    assert "Has a job interview next month" in text
    assert "Practised describing their hospital ward" in text
    assert "{" not in text.replace("{}", "")  # every placeholder filled


async def test_free_talk_brings_profile_and_facts_but_no_episodes(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user_id, tenant_id = await learner(client, db_session)
    for kind, content in (("fact", "Loves hiking"), ("episode", "Talked about pets")):
        await service.add_memory(
            db_session, tenant_id=tenant_id, user_id=user_id, kind=kind, content=content
        )

    text = await call_instructions(app.state.sessionmaker, user_id, None, None)

    assert FREE_OPENING in text and "free talk" in text
    assert "Loves hiking" in text
    assert "Talked about pets" not in text


async def test_a_new_learner_gets_the_default_level_and_only_their_progress(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user_id, _ = await learner(client, db_session)

    text = await call_instructions(app.state.sessionmaker, user_id, None, None)

    assert "The learner's level: A2." in text
    assert "### Where they are now" in text and "- Grammar course: on lesson 1 of" in text
    assert "### Profile" not in text and "Things they have told you" not in text
