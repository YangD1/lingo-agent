"""Tenant-facing usage summaries (P0: per day and model; charts come in P4)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage


@dataclass(frozen=True)
class UsageSummaryRow:
    day: date  # UTC
    connection: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    errors: int
    fallbacks: int
    avg_latency_ms: int


async def summarize_usage(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> list[UsageSummaryRow]:
    day = cast(func.timezone("UTC", LLMUsage.created_at), Date).label("day")
    stmt = (
        select(
            day,
            LLMUsage.connection_name,
            LLMUsage.model,
            func.count(),
            func.coalesce(func.sum(LLMUsage.input_tokens), 0),
            func.coalesce(func.sum(LLMUsage.output_tokens), 0),
            func.count(case((LLMUsage.status == "error", 1))),
            func.count(case((LLMUsage.is_fallback, 1))),
            func.coalesce(func.avg(LLMUsage.latency_ms), 0),
        )
        .where(LLMUsage.tenant_id == tenant_id, LLMUsage.created_at >= since)
        .group_by(day, LLMUsage.connection_name, LLMUsage.model)
        .order_by(day.desc(), LLMUsage.connection_name, LLMUsage.model)
    )
    return [
        UsageSummaryRow(
            day=row[0],
            connection=row[1],
            model=row[2],
            calls=row[3],
            input_tokens=int(row[4]),
            output_tokens=int(row[5]),
            errors=row[6],
            fallbacks=row[7],
            avg_latency_ms=round(row[8]),
        )
        for row in await session.execute(stmt)
    ]
