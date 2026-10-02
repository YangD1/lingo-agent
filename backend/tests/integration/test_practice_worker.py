"""Starting practice sets, generating the next one ahead, and recovery (ADR 0021 §4, Q33e)."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adaptive.exercise.worker import PracticeWorker
from app.adaptive.rules import get_rules
from app.agents.exercise_graph import StructuredCall, build_exercise_graph
from app.auth.service import register_user
from app.db.models import Exercise, ExerciseSet, TenantMember
from app.db.session import create_sessionmaker
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from tests.unit.test_exercise_graph import FakeModels

RULES = get_rules()


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
async def maker(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # db_session's teardown truncates the tables after the test.
    yield create_sessionmaker(db_engine)


async def learner(maker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        user = await register_user(session, f"{uuid.uuid4()}@example.com", "password123")
        tenant_id = await session.scalar(
            select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
        )
        await session.commit()
    assert tenant_id is not None
    return user.id, tenant_id


def worker(
    maker: async_sessionmaker[AsyncSession], models: FakeModels, clock: Clock | None = None
) -> PracticeWorker:
    def calls(
        ctx: TenantProviderContext, config: RunnableConfig
    ) -> tuple[StructuredCall, StructuredCall]:
        assert config["metadata"]["user_id"]  # llm_usage knows whose calls these are
        return models.generate, models.critique

    return PracticeWorker(maker, build_exercise_graph(), calls=calls, clock=clock or Clock())


async def get_set(maker: async_sessionmaker[AsyncSession], set_id: uuid.UUID) -> ExerciseSet:
    async with maker() as session:
        row = await session.get(ExerciseSet, set_id)
    assert row is not None
    return row


async def items(maker: async_sessionmaker[AsyncSession], set_id: uuid.UUID) -> list[Exercise]:
    async with maker() as session:
        rows = await session.scalars(
            select(Exercise).where(Exercise.set_id == set_id, Exercise.status == "ok")
        )
        return list(rows)


async def test_start_generates_a_set_and_reports_progress(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)
    practice = worker(maker, FakeModels())

    set_id = await practice.start(user_id, tenant_id, "dashboard")
    assert practice.stage(set_id) == "generating"
    assert (await get_set(maker, set_id)).status == "generating"
    await practice.wait_idle()

    row = await get_set(maker, set_id)
    assert (row.status, row.origin, row.rules_version) == ("ready", "dashboard", RULES.version)
    assert row.started_at is not None
    assert len(row.kc_plan) == RULES.practice.set_size
    assert {"kc_id", "format", "target_difficulty", "role"} <= set(row.kc_plan[0])
    made = await items(maker, set_id)
    assert len(made) == RULES.practice.set_size
    assert all(i.model == "fake:writer" and i.bank_item_id is None for i in made)
    assert practice.stage(set_id) is None


async def test_a_set_generated_ahead_is_handed_out_without_new_calls(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)
    models = FakeModels()
    practice = worker(maker, models)

    ahead = await practice.prefetch(user_id, tenant_id)
    assert ahead is not None
    assert await practice.prefetch(user_id, tenant_id) is None  # one waiting at most
    await practice.wait_idle()
    row = await get_set(maker, ahead)
    assert (row.status, row.origin, row.started_at) == ("ready", "prefetch", None)
    calls = len(models.generated)

    assert await practice.start(user_id, tenant_id, "learner") == ahead

    assert (await get_set(maker, ahead)).started_at is not None
    assert len(models.generated) == calls
    assert await practice.prefetch(user_id, tenant_id) is not None  # it was taken
    await practice.wait_idle()


async def test_starting_twice_while_generating_gives_the_same_set(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)
    models = FakeModels()
    gate = asyncio.Event()
    generate = models.generate

    async def held(*args: object) -> object:
        await gate.wait()
        return await generate(*args)  # type: ignore[arg-type]

    models.generate = held  # type: ignore[method-assign,assignment]
    practice = worker(maker, models)

    first = await practice.start(user_id, tenant_id, "dashboard")
    assert await practice.start(user_id, tenant_id, "dashboard") == first
    assert await practice.prefetch(user_id, tenant_id) is None
    gate.set()
    await practice.wait_idle()
    assert (await get_set(maker, first)).status == "ready"


@pytest.mark.parametrize("stale", ["age", "rules"])
async def test_stale_sets_generated_ahead_are_replaced(
    maker: async_sessionmaker[AsyncSession], stale: str
) -> None:
    user_id, tenant_id = await learner(maker)
    clock = Clock()
    practice = worker(maker, FakeModels(), clock)
    ahead = await practice.prefetch(user_id, tenant_id)
    assert ahead is not None
    await practice.wait_idle()
    if stale == "age":
        async with maker() as session:
            created = (await session.get(ExerciseSet, ahead)).created_at  # type: ignore[union-attr]
        clock.now = created + timedelta(hours=RULES.practice.prefetch_max_hours, minutes=1)
    else:
        async with maker() as session:
            await session.execute(
                update(ExerciseSet).where(ExerciseSet.id == ahead).values(rules_version="old")
            )
            await session.commit()

    fresh = await practice.start(user_id, tenant_id, "dashboard")
    await practice.wait_idle()

    assert fresh != ahead
    old = await get_set(maker, ahead)
    assert (old.status, old.error_code) == ("failed", "expired")
    assert (await get_set(maker, fresh)).status == "ready"


async def test_without_a_model_the_set_comes_from_the_bank(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)
    models = FakeModels(generate_error=NoModelConfiguredError("llm", "exercise_generate", []))
    practice = worker(maker, models)

    set_id = await practice.start(user_id, tenant_id, "dashboard")
    await practice.wait_idle()

    assert (await get_set(maker, set_id)).status == "ready"
    made = await items(maker, set_id)
    assert len(made) == RULES.practice.set_size
    assert all(i.bank_item_id is not None and i.format == "choice4" for i in made)


async def test_an_unexpected_error_fails_the_set(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)

    def broken(
        ctx: TenantProviderContext, config: RunnableConfig
    ) -> tuple[StructuredCall, StructuredCall]:
        raise RuntimeError("bug")

    practice = PracticeWorker(maker, build_exercise_graph(), calls=broken)
    set_id = await practice.start(user_id, tenant_id, "dashboard")
    await practice.wait_idle()

    row = await get_set(maker, set_id)
    assert (row.status, row.error_code) == ("failed", "generation_failed")


async def test_recover_fails_sets_cut_off_by_a_restart(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, _ = await learner(maker)
    async with maker() as session:
        row = ExerciseSet(user_id=user_id, origin="dashboard", status="generating", kc_plan=[])
        session.add(row)
        await session.commit()

    assert await worker(maker, FakeModels()).recover() == 1

    found = await get_set(maker, row.id)
    assert (found.status, found.error_code) == ("failed", "interrupted")


async def test_prefetch_can_be_switched_off(maker: async_sessionmaker[AsyncSession]) -> None:
    user_id, tenant_id = await learner(maker)
    practice = worker(maker, FakeModels())
    practice.prefetch_enabled = False

    assert await practice.prefetch(user_id, tenant_id) is None
