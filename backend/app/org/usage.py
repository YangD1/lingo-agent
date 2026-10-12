"""How much of their quotas a member has used on their main account (ADR 0031 §4, §6).

Counted from `llm_usage` rows the member's tenant made on the main account's
connections (tokens, characters, audio seconds) and realtime calls on them
(`speaking_sessions.call_seconds`), per UTC day and month. Checked when work starts,
not per token: the last call may go a little past a cap, like the background budget
(ADR 0025).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage, OrgMembership, SpeakingSession
from app.org.quotas import CAPABILITIES, SECTIONS, UNITS, Capability, Limit, Quotas


@dataclass(frozen=True)
class Used:
    """In the capability's unit: tokens, characters or minutes."""

    day: float = 0.0
    month: float = 0.0


def day_start(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(UTC).date(), time.min, UTC)


def month_start(now: datetime) -> datetime:
    return day_start(now).replace(day=1)


async def used(
    session: AsyncSession,
    sponsor_tenant_id: uuid.UUID,
    member_tenant_id: uuid.UUID,
    member_user_id: uuid.UUID,
    now: datetime,
) -> dict[Capability, Used]:
    """This month's and today's use of each capability on the main account."""
    day, month = day_start(now), month_start(now)
    amount: dict[Capability, ColumnElement[Any]] = {
        "text": LLMUsage.input_tokens + LLMUsage.output_tokens,
        "tts": func.coalesce(LLMUsage.characters, 0),
        "asr": func.coalesce(LLMUsage.audio_seconds, 0.0) / 60,
        "pronunciation": func.coalesce(LLMUsage.audio_seconds, 0.0) / 60,
    }
    columns = []
    for capability, value in amount.items():
        in_capability = LLMUsage.section.in_(SECTIONS[capability])
        columns += [
            func.coalesce(func.sum(value).filter(in_capability), 0),
            func.coalesce(func.sum(value).filter(in_capability, LLMUsage.created_at >= day), 0),
        ]
    row = (
        await session.execute(
            select(*columns).where(
                LLMUsage.billed_tenant_id == sponsor_tenant_id,
                LLMUsage.tenant_id == member_tenant_id,
                LLMUsage.created_at >= month,
            )
        )
    ).one()
    out: dict[Capability, Used] = {
        capability: Used(day=float(row[2 * i + 1]), month=float(row[2 * i]))
        for i, capability in enumerate(amount)
    }
    minutes = SpeakingSession.call_seconds / 60
    calls = (
        await session.execute(
            select(
                func.coalesce(func.sum(minutes), 0.0),
                func.coalesce(func.sum(minutes).filter(SpeakingSession.started_at >= day), 0.0),
            ).where(
                SpeakingSession.billed_tenant_id == sponsor_tenant_id,
                SpeakingSession.user_id == member_user_id,
                SpeakingSession.mode == "realtime",
                SpeakingSession.started_at >= month,
            )
        )
    ).one()
    out["realtime"] = Used(day=float(calls[1]), month=float(calls[0]))
    return out


def left(limit: Limit, use: Used) -> float | None:
    """What's left under the tighter cap, never below 0; None: no cap."""
    caps = [
        cap - spent
        for cap, spent in ((limit.daily, use.day), (limit.monthly, use.month))
        if cap is not None
    ]
    return max(0.0, min(caps)) if caps else None


async def membership_use(
    session: AsyncSession, membership: OrgMembership, now: datetime
) -> dict[Capability, Used]:
    return await used(
        session,
        membership.sponsor_tenant_id,
        membership.member_tenant_id,
        membership.member_user_id,
        now,
    )


async def exhausted_sections(
    session: AsyncSession, membership: OrgMembership, now: datetime
) -> frozenset[str]:
    """Sections the member may not use the main account's models for right now."""
    quotas = Quotas.model_validate(membership.quotas)
    use = await membership_use(session, membership, now)
    out: set[str] = set()
    for capability in CAPABILITIES:
        remaining = left(quotas.limit(capability), use[capability])
        if remaining is not None and remaining <= 0:
            out.update(SECTIONS[capability])
    return frozenset(out)


async def realtime_seconds_left(
    session: AsyncSession, membership: OrgMembership, now: datetime
) -> float | None:
    """How long a call on the main account's connection may still last; None: no cap."""
    assert UNITS["realtime"] == "minutes"
    quotas = Quotas.model_validate(membership.quotas)
    use = await membership_use(session, membership, now)
    minutes = left(quotas.realtime, use["realtime"])
    return None if minutes is None else minutes * 60
