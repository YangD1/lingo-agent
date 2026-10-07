"""Background work settings (ADR 0025 §5-6): the learner's switches, the tenant's budget."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import api_error
from app.db.models import SchedulerRun
from app.deps import CurrentTenant, CurrentUser, Manager, SessionDep
from app.scheduler import budget, prefs
from app.scheduler.service import Scheduler

router = APIRouter(tags=["background"])

MAX_DAILY_TOKENS = 100_000_000

# ok: background work runs; exhausted: today's budget is used up, it runs again
# tomorrow (UTC); off: the tenant set the budget to 0.
BudgetState = Literal["ok", "exhausted", "off"]


def get_scheduler(request: Request) -> Scheduler:
    scheduler: Scheduler = request.app.state.scheduler
    return scheduler


SchedulerDep = Annotated[Scheduler, Depends(get_scheduler)]


def budget_state(found: budget.Budget) -> BudgetState:
    if found.limit == 0:
        return "off"
    return "exhausted" if found.exhausted else "ok"


class BackgroundFeatureOut(BaseModel):
    key: str
    enabled: bool
    default: bool
    # The `features.yaml` feature whose estimates its AI badge shows.
    usage_feature: str


class MyBackgroundOut(BaseModel):
    features: list[BackgroundFeatureOut]
    budget: BudgetState


async def _mine(session: SessionDep, user: CurrentUser, tenant: CurrentTenant) -> MyBackgroundOut:
    switches = await prefs.load(session, user.id)
    found = await budget.load(session, tenant.id, datetime.now(UTC))
    return MyBackgroundOut(
        features=[
            BackgroundFeatureOut(
                key=f.key, enabled=switches[f.key], default=f.default, usage_feature=f.usage_feature
            )
            for f in prefs.FEATURES
        ],
        budget=budget_state(found),
    )


@router.get("/me/background")
async def my_background(
    user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> MyBackgroundOut:
    """What the tutor may do for this learner in the background, and whether it can today."""
    return await _mine(session, user, tenant)


class SwitchIn(BaseModel):
    enabled: bool


@router.put("/me/background/{feature}")
async def set_my_background(
    feature: str, body: SwitchIn, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> MyBackgroundOut:
    try:
        await prefs.set_enabled(session, user.id, feature, body.enabled)
    except prefs.UnknownFeatureError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "feature_not_found", f"no background feature {feature}"
        ) from exc
    await session.commit()
    return await _mine(session, user, tenant)


class JobOut(BaseModel):
    job: str
    next_run_at: datetime | None
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_success_at: datetime | None
    last_status: str | None
    last_skip_reason: str | None
    last_error: str | None


class TenantBackgroundOut(BaseModel):
    daily_tokens: int
    used_today: int
    budget: BudgetState
    scheduler_running: bool
    jobs: list[JobOut]


async def _tenant(
    session: SessionDep, tenant: CurrentTenant, scheduler: Scheduler
) -> TenantBackgroundOut:
    found = await budget.load(session, tenant.id, datetime.now(UTC))
    names = scheduler.job_names
    rows = {
        row.job: row
        for row in await session.scalars(select(SchedulerRun).where(SchedulerRun.job.in_(names)))
    }
    jobs = []
    for name in names:
        row = rows.get(name)
        jobs.append(
            JobOut(
                job=name,
                next_run_at=scheduler.next_run(name),
                last_started_at=row.last_started_at if row else None,
                last_finished_at=row.last_finished_at if row else None,
                last_success_at=row.last_success_at if row else None,
                last_status=row.last_status if row else None,
                last_skip_reason=row.last_skip_reason if row else None,
                last_error=row.last_error if row else None,
            )
        )
    return TenantBackgroundOut(
        daily_tokens=found.limit,
        used_today=found.used,
        budget=budget_state(found),
        scheduler_running=scheduler.running,
        jobs=jobs,
    )


@router.get("/tenant/background", dependencies=[Manager])
async def tenant_background(
    tenant: CurrentTenant, session: SessionDep, scheduler: SchedulerDep
) -> TenantBackgroundOut:
    """The daily background budget, today's use (UTC) and how scheduled jobs last went."""
    return await _tenant(session, tenant, scheduler)


class BudgetIn(BaseModel):
    daily_tokens: int = Field(ge=0, le=MAX_DAILY_TOKENS)


@router.put("/tenant/background", dependencies=[Manager])
async def set_tenant_background(
    body: BudgetIn, tenant: CurrentTenant, session: SessionDep, scheduler: SchedulerDep
) -> TenantBackgroundOut:
    tenant.background_daily_tokens = body.daily_tokens
    await session.commit()
    return await _tenant(session, tenant, scheduler)
