"""A learner's own AI use this month (ADR 0034 §4), per capability in its quota unit
(ADR 0031 §4): their own tenant's calls and those on a main account's connections.
No costs: those are for whoever pays.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage, SpeakingSession
from app.org.quotas import CAPABILITIES, SECTIONS, Capability
from app.org.usage import month_start


async def month_use(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> dict[Capability, float]:
    since = month_start(now)
    amount: dict[Capability, ColumnElement[Any]] = {
        "text": LLMUsage.input_tokens + LLMUsage.output_tokens,
        "tts": func.coalesce(LLMUsage.characters, 0),
        "asr": func.coalesce(LLMUsage.audio_seconds, 0.0) / 60,
        "pronunciation": func.coalesce(LLMUsage.audio_seconds, 0.0) / 60,
    }

    def in_capability(capability: Capability) -> ColumnElement[bool]:
        sections = LLMUsage.section.in_(SECTIONS[capability])
        # Rows from before sections were recorded (ADR 0031 §6) were text, bar the
        # characters and audio they carry.
        return or_(sections, LLMUsage.section.is_(None)) if capability == "text" else sections

    row = (
        await session.execute(
            select(
                *(
                    func.coalesce(func.sum(value).filter(in_capability(capability)), 0)
                    for capability, value in amount.items()
                )
            ).where(
                LLMUsage.tenant_id == tenant_id,
                LLMUsage.user_id == user_id,
                LLMUsage.created_at >= since,
            )
        )
    ).one()
    out: dict[Capability, float] = {c: float(v) for c, v in zip(amount, row, strict=True)}
    # Like the quota, call minutes come from the calls themselves.
    out["realtime"] = float(
        await session.scalar(
            select(func.coalesce(func.sum(SpeakingSession.call_seconds), 0.0) / 60).where(
                SpeakingSession.user_id == user_id,
                SpeakingSession.mode == "realtime",
                SpeakingSession.started_at >= since,
            )
        )
        or 0.0
    )
    assert set(out) == set(CAPABILITIES)
    return out
