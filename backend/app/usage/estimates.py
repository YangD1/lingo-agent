"""Per-feature usage estimates for the AI badge (ADR 0014): the tenant's recent
successful calls of each task, averaged, or the catalog's defaults without history."""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage
from app.providers.config import ProvidersConfig, TenantProviderContext, resolve_route
from app.providers.errors import NoModelConfiguredError, ProviderConfigError
from app.usage.features import FeatureCall, FeatureCatalog, Per, Timing

EstimateSource = Literal["history", "default"]


@dataclass(frozen=True)
class TaskHistory:
    samples: int
    input_tokens: int
    output_tokens: int
    audio_seconds: float | None


@dataclass(frozen=True)
class CallEstimate:
    task: str
    timing: Timing
    per: Per
    input_tokens: int
    output_tokens: int
    audio_seconds: float | None
    samples: int
    source: EstimateSource
    # "<connection>:<model>" the call would run on now; None when none is configured.
    model: str | None


@dataclass(frozen=True)
class FeatureEstimate:
    feature: str
    calls: list[CallEstimate]


def estimate_call(
    call: FeatureCall, history: TaskHistory | None, model: str | None
) -> CallEstimate:
    if history is None or history.samples == 0:
        return CallEstimate(
            task=call.task,
            timing=call.timing,
            per=call.per,
            input_tokens=call.default.input_tokens,
            output_tokens=call.default.output_tokens,
            audio_seconds=call.default.audio_seconds,
            samples=0,
            source="default",
            model=model,
        )
    return CallEstimate(
        task=call.task,
        timing=call.timing,
        per=call.per,
        input_tokens=history.input_tokens,
        output_tokens=history.output_tokens,
        audio_seconds=history.audio_seconds,
        samples=history.samples,
        source="history",
        model=model,
    )


async def task_history(
    session: AsyncSession, tenant_id: uuid.UUID, task: str, *, audio: bool, window: int
) -> TaskHistory:
    """Averages over the task's last `window` successful calls that reported usage."""
    reported = LLMUsage.audio_seconds.is_not(None) if audio else LLMUsage.input_tokens > 0
    recent = (
        select(LLMUsage.input_tokens, LLMUsage.output_tokens, LLMUsage.audio_seconds)
        .where(
            LLMUsage.tenant_id == tenant_id,
            LLMUsage.task == task,
            LLMUsage.status == "ok",
            reported,
        )
        .order_by(LLMUsage.created_at.desc(), LLMUsage.id.desc())
        .limit(window)
        .subquery()
    )
    row = (
        await session.execute(
            select(
                func.count(),
                func.avg(recent.c.input_tokens),
                func.avg(recent.c.output_tokens),
                func.avg(recent.c.audio_seconds),
            )
        )
    ).one()
    samples = int(row[0])
    return TaskHistory(
        samples=samples,
        input_tokens=round(row[1] or 0),
        output_tokens=round(row[2] or 0),
        audio_seconds=round(float(row[3]), 1) if row[3] is not None else None,
    )


def current_model(
    config: ProvidersConfig, ctx: TenantProviderContext, call: FeatureCall
) -> str | None:
    try:
        first = resolve_route(config, ctx, call.section, call.route_task)[0]
    except (NoModelConfiguredError, ProviderConfigError):
        return None
    return f"{first.connection}:{first.model}"


async def feature_estimates(
    session: AsyncSession,
    catalog: FeatureCatalog,
    config: ProvidersConfig,
    ctx: TenantProviderContext,
) -> list[FeatureEstimate]:
    histories: dict[str, TaskHistory] = {}
    for feature in catalog.features.values():
        for call in feature.calls:
            if call.history and call.task not in histories:
                histories[call.task] = await task_history(
                    session,
                    ctx.tenant_id,
                    call.task,
                    audio=call.section == "asr",
                    window=catalog.window,
                )
    return [
        FeatureEstimate(
            feature=name,
            calls=[
                estimate_call(call, histories.get(call.task), current_model(config, ctx, call))
                for call in feature.calls
            ],
        )
        for name, feature in catalog.features.items()
    ]
