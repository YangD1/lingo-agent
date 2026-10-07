"""The tenant's daily budget for background model calls (ADR 0025 §5).

Counts the tokens of `llm_usage` rows marked `background` since midnight UTC. Work
checks the budget before it starts and may finish past it (Q40b): the budget guards
cost, it is not exact. Calls a learner is waiting for are never counted or stopped.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage, Tenant

EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class Budget:
    limit: int
    used: int

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit  # a limit of 0 is always exhausted


def day_start(now: datetime) -> datetime:
    """Midnight UTC of `now`'s day (`now` must be timezone-aware)."""
    return datetime.combine(now.astimezone(UTC).date(), time.min, UTC)


async def used_today(session: AsyncSession, tenant_id: uuid.UUID, now: datetime) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(LLMUsage.input_tokens + LLMUsage.output_tokens), 0)).where(
            LLMUsage.tenant_id == tenant_id,
            LLMUsage.background.is_(True),
            LLMUsage.created_at >= day_start(now),
        )
    )
    return int(total or 0)


async def load(session: AsyncSession, tenant_id: uuid.UUID, now: datetime) -> Budget:
    limit = await session.scalar(
        select(Tenant.background_daily_tokens).where(Tenant.id == tenant_id)
    )
    return Budget(limit=limit or 0, used=await used_today(session, tenant_id, now))
