"""Tenant LLM usage (ADR 0005 §A, ADR 0034): counts, no content; costs only from prices
the tenant entered."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.deps import CurrentTenant, CurrentUser, Manager, SessionDep
from app.providers.llm import get_providers_config
from app.providers.tenant import load_provider_context
from app.usage.dashboard import usage_dashboard
from app.usage.estimates import EstimateSource, feature_estimates
from app.usage.features import Per, Timing, get_features
from app.usage.service import summarize_usage

router = APIRouter(tags=["usage"])


class UsageRowOut(BaseModel):
    day: date
    connection: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    characters: int
    errors: int
    fallbacks: int
    avg_latency_ms: int
    # None: this account's own calls; else a member's on its connections (ADR 0031 §8).
    member: str | None


class UsageOut(BaseModel):
    days: int
    rows: list[UsageRowOut]


@router.get("/tenant/usage", dependencies=[Manager])
async def tenant_usage(
    tenant: CurrentTenant,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> UsageOut:
    """Per UTC day and model over the last `days` days (today included), the account's
    own calls and each member's on its connections apart."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=days - 1)
    rows = await summarize_usage(session, tenant.id, since)
    return UsageOut(days=days, rows=[UsageRowOut.model_validate(r.__dict__) for r in rows])


class TallyOut(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    characters: int
    audio_minutes: float
    errors: int
    fallbacks: int
    # None: nothing in it was priced (ADR 0034 §3).
    cost: float | None
    # Some usage in it had no price, so `cost` leaves it out.
    cost_partial: bool


class DayTallyOut(TallyOut):
    day: date


class TaskTallyOut(TallyOut):
    task: str
    background: bool


class ModelTallyOut(TallyOut):
    connection: str
    model: str


class MemberTallyOut(TallyOut):
    member: str | None


class UsageDashboardOut(BaseModel):
    days: int
    total: TallyOut
    series: list[DayTallyOut]
    tasks: list[TaskTallyOut]
    models: list[ModelTallyOut]
    members: list[MemberTallyOut]
    priced: bool


@router.get("/tenant/usage/dashboard", dependencies=[Manager])
async def tenant_usage_dashboard(
    tenant: CurrentTenant,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> UsageDashboardOut:
    """Totals, a daily series and per-task / model / member groups over the last `days`
    UTC days (today included), same scope as `/tenant/usage` (ADR 0034 §2)."""
    today = datetime.now(UTC).date()
    board = await usage_dashboard(session, tenant.id, today - timedelta(days=days - 1), today, {})
    return UsageDashboardOut(
        days=days,
        total=TallyOut.model_validate(board.total.__dict__),
        series=[DayTallyOut(day=d.day, **d.tally.__dict__) for d in board.days],
        tasks=[
            TaskTallyOut(task=t.task, background=t.background, **t.tally.__dict__)
            for t in board.tasks
        ],
        models=[
            ModelTallyOut(connection=m.connection, model=m.model, **m.tally.__dict__)
            for m in board.models
        ],
        members=[MemberTallyOut(member=m.member, **m.tally.__dict__) for m in board.members],
        priced=board.priced,
    )


class CallEstimateOut(BaseModel):
    task: str
    timing: Timing
    per: Per
    input_tokens: int
    output_tokens: int
    audio_seconds: float | None
    characters: int | None
    samples: int
    source: EstimateSource
    model: str | None
    provided_by: str | None


class FeatureEstimateOut(BaseModel):
    feature: str
    calls: list[CallEstimateOut]


class UsageEstimatesOut(BaseModel):
    window: int
    features: list[FeatureEstimateOut]


@router.get("/usage/estimates")
async def usage_estimates(
    _: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> UsageEstimatesOut:
    """What each AI feature calls and roughly how many tokens (ADR 0014)."""
    catalog = get_features()
    ctx = await load_provider_context(session, tenant.id)
    estimates = await feature_estimates(session, catalog, get_providers_config(), ctx)
    return UsageEstimatesOut(
        window=catalog.window,
        features=[
            FeatureEstimateOut(
                feature=e.feature,
                calls=[CallEstimateOut.model_validate(c.__dict__) for c in e.calls],
            )
            for e in estimates
        ],
    )
