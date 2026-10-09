"""Tenant LLM usage (ADR 0005 §A): token counts only, no prices, no content."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.deps import CurrentTenant, CurrentUser, Manager, SessionDep
from app.providers.llm import get_providers_config
from app.providers.tenant import load_provider_context
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
