"""Counting today's background tokens per tenant (ADR 0025 §5)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.service import register_user
from app.db.models import LLMUsage, Tenant, TenantMember
from app.db.session import create_sessionmaker
from app.scheduler import budget

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
async def maker(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # db_session's teardown truncates the tables after the test.
    yield create_sessionmaker(db_engine)


async def tenant(session: AsyncSession) -> uuid.UUID:
    user = await register_user(session, f"{uuid.uuid4()}@example.com", "password123")
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
    )
    assert tenant_id is not None
    return tenant_id


def usage(tenant_id: uuid.UUID, tokens: int, *, background: bool, at: datetime) -> LLMUsage:
    return LLMUsage(
        tenant_id=tenant_id,
        task="exercise_generate",
        connection_name="c",
        model="m",
        input_tokens=tokens,
        output_tokens=tokens,
        latency_ms=1,
        status="ok",
        background=background,
        created_at=at,
    )


async def test_counts_only_todays_background_calls_of_the_tenant(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as session:
        mine, other = await tenant(session), await tenant(session)
        session.add_all(
            [
                usage(mine, 100, background=True, at=NOW - timedelta(hours=1)),
                usage(mine, 50, background=True, at=NOW.replace(hour=0)),  # midnight counts
                usage(mine, 1000, background=False, at=NOW),  # the learner was waiting
                usage(mine, 1000, background=True, at=NOW.replace(hour=0) - timedelta(seconds=1)),
                usage(other, 1000, background=True, at=NOW),
            ]
        )
        await session.commit()

        found = await budget.load(session, mine, NOW)
    assert found == budget.Budget(limit=300_000, used=300)
    assert not found.exhausted


async def test_the_limit_is_the_tenants(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as session:
        tenant_id = await tenant(session)
        await session.execute(
            update(Tenant).where(Tenant.id == tenant_id).values(background_daily_tokens=0)
        )
        await session.commit()
        found = await budget.load(session, tenant_id, NOW)
    assert found == budget.Budget(limit=0, used=0)
    assert found.exhausted
