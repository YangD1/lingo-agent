"""Tenant LLM usage (ADR 0005 §A): token counts only, no prices, no content."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.deps import CurrentTenant, Manager, SessionDep
from app.usage.service import summarize_usage

router = APIRouter(tags=["usage"])


class UsageRowOut(BaseModel):
    day: date
    connection: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    errors: int
    fallbacks: int
    avg_latency_ms: int


class UsageOut(BaseModel):
    days: int
    rows: list[UsageRowOut]


@router.get("/tenant/usage", dependencies=[Manager])
async def tenant_usage(
    tenant: CurrentTenant,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> UsageOut:
    """Per UTC day and model over the last `days` days (today included)."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=days - 1)
    rows = await summarize_usage(session, tenant.id, since)
    return UsageOut(days=days, rows=[UsageRowOut.model_validate(r.__dict__) for r in rows])
