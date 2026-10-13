"""Tenant LLM usage (ADR 0005 §A, ADR 0034): counts, no content; costs only from prices
the tenant entered."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator

from app.db.models import Tenant
from app.deps import CurrentTenant, CurrentUser, Manager, SessionDep
from app.org import service as org
from app.org import usage as org_usage
from app.org.quotas import CAPABILITIES, UNITS, Capability, Quotas
from app.providers.llm import get_providers_config
from app.providers.tenant import load_provider_context
from app.usage.dashboard import Price, usage_dashboard
from app.usage.estimates import EstimateSource, feature_estimates
from app.usage.features import Per, Timing, get_features
from app.usage.mine import month_use
from app.usage.prices import load_prices, replace_prices
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
    currency: str


@router.get("/tenant/usage/dashboard", dependencies=[Manager])
async def tenant_usage_dashboard(
    tenant: CurrentTenant,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> UsageDashboardOut:
    """Totals, a daily series and per-task / model / member groups over the last `days`
    UTC days (today included), same scope as `/tenant/usage` (ADR 0034 §2)."""
    today = datetime.now(UTC).date()
    prices = await load_prices(session, tenant.id)
    board = await usage_dashboard(
        session, tenant.id, today - timedelta(days=days - 1), today, prices
    )
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
        currency=tenant.price_currency,
    )


Currency = Literal["CNY", "USD"]
UnitPrice = Annotated[float, Field(ge=0, le=1_000_000)] | None


class ModelPriceIO(BaseModel):
    connection: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    input_per_mtok: UnitPrice = None
    output_per_mtok: UnitPrice = None
    per_kchar: UnitPrice = None
    per_minute: UnitPrice = None


class PricesIO(BaseModel):
    currency: Currency
    prices: list[ModelPriceIO] = Field(max_length=500)

    @model_validator(mode="after")
    def _one_per_model(self) -> "PricesIO":
        keys = [(p.connection, p.model) for p in self.prices]
        if len(keys) != len(set(keys)):
            raise ValueError("one price per connection and model")
        return self


async def _prices_out(session: SessionDep, tenant: CurrentTenant) -> PricesIO:
    prices = await load_prices(session, tenant.id)
    return PricesIO(
        currency=tenant.price_currency,
        prices=[
            ModelPriceIO(connection=connection, model=model, **price.__dict__)
            for (connection, model), price in sorted(prices.items())
        ],
    )


@router.get("/tenant/prices", dependencies=[Manager])
async def tenant_prices(tenant: CurrentTenant, session: SessionDep) -> PricesIO:
    """The prices this account entered (ADR 0034 §3); nothing is built in."""
    return await _prices_out(session, tenant)


@router.put("/tenant/prices", dependencies=[Manager])
async def set_tenant_prices(body: PricesIO, tenant: CurrentTenant, session: SessionDep) -> PricesIO:
    """Replaces the whole list; a model with no price entered is dropped."""
    tenant.price_currency = body.currency
    await replace_prices(
        session,
        tenant.id,
        [
            (
                p.connection,
                p.model,
                Price(
                    input_per_mtok=p.input_per_mtok,
                    output_per_mtok=p.output_per_mtok,
                    per_kchar=p.per_kchar,
                    per_minute=p.per_minute,
                ),
            )
            for p in body.prices
        ],
    )
    await session.commit()
    return await _prices_out(session, tenant)


class QuotaUseOut(BaseModel):
    """On the main account's connections, today and this month (UTC)."""

    daily: int | None
    monthly: int | None
    day: float
    month: float
    # Under the tighter cap; None: no cap.
    left: float | None


class CapabilityUseOut(BaseModel):
    capability: Capability
    unit: Literal["tokens", "characters", "minutes"]
    # All of this month's use, on any connection.
    month: float
    # Only for a member (ADR 0031): their quota from the main account.
    quota: QuotaUseOut | None


class MyUsageOut(BaseModel):
    month_start: date
    sponsor_name: str | None
    capabilities: list[CapabilityUseOut]


@router.get("/me/usage")
async def my_usage(user: CurrentUser, tenant: CurrentTenant, session: SessionDep) -> MyUsageOut:
    """The learner's own AI use this UTC month, and quotas left if a member; no costs
    (ADR 0034 §4)."""
    now = datetime.now(UTC)
    mine = await month_use(session, tenant.id, user.id, now)
    membership = await org.active_membership(session, tenant.id)
    quotas: Quotas | None = None
    sponsored: dict[Capability, org_usage.Used] = {}
    sponsor_name: str | None = None
    if membership is not None:
        quotas = Quotas.model_validate(membership.quotas)
        sponsored = await org_usage.membership_use(session, membership, now)
        sponsor = await session.get(Tenant, membership.sponsor_tenant_id)
        sponsor_name = sponsor.name if sponsor is not None else None

    def quota(capability: Capability) -> QuotaUseOut | None:
        if quotas is None:
            return None
        limit, use = quotas.limit(capability), sponsored[capability]
        left = org_usage.left(limit, use)
        return QuotaUseOut(
            daily=limit.daily,
            monthly=limit.monthly,
            day=round(use.day, 2),
            month=round(use.month, 2),
            left=None if left is None else round(left, 2),
        )

    return MyUsageOut(
        month_start=org_usage.month_start(now).date(),
        sponsor_name=sponsor_name,
        capabilities=[
            CapabilityUseOut(capability=c, unit=UNITS[c], month=round(mine[c], 2), quota=quota(c))
            for c in CAPABILITIES
        ],
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
