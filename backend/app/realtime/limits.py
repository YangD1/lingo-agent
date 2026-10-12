"""How long a learner may talk on a realtime call (ADR 0030 §5, Q60f-h).

The tenant sets one call's length and each learner's minutes per UTC day (same day as
the background budget, ADR 0025); either at 0 turns calls off. A day's minutes are the
calls' connected time, not just the learner's speech: the vendor bills the whole call.
A call may last the shorter of the two limits; with under a minute left today, none
starts.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SpeakingSession, Tenant
from app.org.service import active_membership
from app.org.usage import realtime_seconds_left
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from app.providers.realtime import get_realtime

# A call shorter than this isn't worth connecting.
MIN_CALL_SECONDS = 60
# How long before the end the learner is told time is nearly up.
WARNING_SECONDS = 60

type LimitState = Literal["ok", "used_up", "off"]


@dataclass(frozen=True)
class CallLimit:
    session_minutes: int
    daily_minutes: int
    used_seconds: float  # today, by this learner
    state: LimitState
    # How long the next call may last; 0 unless `state` is ok.
    allowed_seconds: int


def day_start(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)


async def used_today(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> float:
    total = await session.scalar(
        select(func.coalesce(func.sum(SpeakingSession.call_seconds), 0.0)).where(
            SpeakingSession.user_id == user_id,
            SpeakingSession.mode == "realtime",
            SpeakingSession.started_at >= day_start(now),
        )
    )
    return float(total or 0.0)


async def call_limit(
    session: AsyncSession, tenant: Tenant, user_id: uuid.UUID, now: datetime
) -> CallLimit:
    used = await used_today(session, user_id, now)
    session_minutes, daily_minutes = tenant.realtime_session_minutes, tenant.realtime_daily_minutes
    if session_minutes == 0 or daily_minutes == 0:
        state: LimitState = "off"
        allowed = 0
    else:
        allowed = int(min(session_minutes * 60, daily_minutes * 60 - used))
        state = "ok" if allowed >= MIN_CALL_SECONDS else "used_up"
    return CallLimit(
        session_minutes=session_minutes,
        daily_minutes=daily_minutes,
        used_seconds=used,
        state=state,
        allowed_seconds=allowed if state == "ok" else 0,
    )


async def quota_seconds_left(
    session: AsyncSession, ctx: TenantProviderContext, now: datetime
) -> float | None:
    """How long a call may last on a member's realtime quota (ADR 0031 §6); None when the
    call wouldn't use the main account's connection, or the quota has no cap."""
    try:
        route = get_realtime(ctx)
    except NoModelConfiguredError:
        return None
    if route.targets[0].model.billed_tenant_id is None:
        return None
    membership = await active_membership(session, ctx.tenant_id)
    if membership is None:  # left since the context was loaded
        return None
    return await realtime_seconds_left(session, membership, now)
