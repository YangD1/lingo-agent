"""Per-feature usage estimates for the AI badge (ADR 0014): the tenant's recent
successful calls of each task, averaged, or the catalog's defaults without history."""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, LLMUsage, SpeakingSession
from app.providers.config import ProvidersConfig, TenantProviderContext, resolve_route
from app.providers.errors import NoModelConfiguredError, ProviderConfigError
from app.usage.features import AUDIO_SECTIONS, FeatureCall, FeatureCatalog, Per, Timing

EstimateSource = Literal["history", "default"]
# What a call is billed by: speech-to-text and pronunciation assessment by audio length,
# text-to-speech by characters.
Unit = Literal["tokens", "audio", "characters"]


def unit_of(call: FeatureCall) -> Unit:
    if call.section in AUDIO_SECTIONS:
        return "audio"
    if call.section == "tts":
        return "characters"
    return "tokens"


@dataclass(frozen=True)
class TaskHistory:
    samples: int
    input_tokens: int
    output_tokens: int
    audio_seconds: float | None
    characters: int | None = None


@dataclass(frozen=True)
class CallEstimate:
    task: str
    timing: Timing
    per: Per
    input_tokens: int
    output_tokens: int
    audio_seconds: float | None
    characters: int | None
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
            characters=call.default.characters,
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
        characters=history.characters,
        samples=history.samples,
        source="history",
        model=model,
    )


async def task_history(
    session: AsyncSession, tenant_id: uuid.UUID, task: str, *, unit: Unit, window: int
) -> TaskHistory:
    """Averages over the task's last `window` successful calls that reported usage."""
    reported = {
        "audio": LLMUsage.audio_seconds.is_not(None),
        "characters": LLMUsage.characters.is_not(None),
        "tokens": LLMUsage.input_tokens > 0,
    }[unit]
    recent = (
        select(
            LLMUsage.input_tokens,
            LLMUsage.output_tokens,
            LLMUsage.audio_seconds,
            LLMUsage.characters,
        )
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
                func.avg(recent.c.characters),
            )
        )
    ).one()
    samples = int(row[0])
    return TaskHistory(
        samples=samples,
        input_tokens=round(row[1] or 0),
        output_tokens=round(row[2] or 0),
        audio_seconds=round(float(row[3]), 1) if row[3] is not None else None,
        characters=round(row[4]) if row[4] is not None else None,
    )


# Calls shorter than this say more about connecting than about talking.
MIN_CALL_SECONDS = 30.0


async def minute_history(
    session: AsyncSession, tenant_id: uuid.UUID, task: str, *, window: int
) -> TaskHistory:
    """Tokens per minute over the tenant's last `window` finished realtime calls: their
    usage rows (one per reply) summed, over the calls' own length (ADR 0030 §6)."""
    calls = (
        select(SpeakingSession.conversation_id, SpeakingSession.call_seconds)
        .join(Conversation, Conversation.id == SpeakingSession.conversation_id)
        .where(
            Conversation.tenant_id == tenant_id,
            SpeakingSession.mode == "realtime",
            # Hung up; the summary may still be coming (task 61.3).
            SpeakingSession.ended_at.is_not(None),
            SpeakingSession.call_seconds >= MIN_CALL_SECONDS,
        )
        .order_by(SpeakingSession.ended_at.desc(), SpeakingSession.id.desc())
        .limit(window)
        .subquery()
    )
    used = (
        select(
            LLMUsage.conversation_id,
            func.sum(LLMUsage.input_tokens).label("input_tokens"),
            func.sum(LLMUsage.output_tokens).label("output_tokens"),
        )
        .where(LLMUsage.tenant_id == tenant_id, LLMUsage.task == task, LLMUsage.status == "ok")
        .group_by(LLMUsage.conversation_id)
        .subquery()
    )
    row = (
        await session.execute(
            select(
                func.count(),
                func.sum(calls.c.call_seconds),
                func.sum(used.c.input_tokens),
                func.sum(used.c.output_tokens),
            ).select_from(calls.join(used, used.c.conversation_id == calls.c.conversation_id))
        )
    ).one()
    samples = int(row[0])
    if samples == 0:
        return TaskHistory(samples=0, input_tokens=0, output_tokens=0, audio_seconds=None)
    minutes = float(row[1]) / 60
    return TaskHistory(
        samples=samples,
        input_tokens=round(int(row[2] or 0) / minutes),
        output_tokens=round(int(row[3] or 0) / minutes),
        audio_seconds=None,
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
    # By task and what one estimate covers: a minute of a call is not one call.
    histories: dict[tuple[str, Per], TaskHistory] = {}
    for feature in catalog.features.values():
        for call in feature.calls:
            key = (call.task, call.per)
            if not call.history or key in histories:
                continue
            if call.per == "minute":
                histories[key] = await minute_history(
                    session, ctx.tenant_id, call.task, window=catalog.window
                )
            else:
                histories[key] = await task_history(
                    session,
                    ctx.tenant_id,
                    call.task,
                    unit=unit_of(call),
                    window=catalog.window,
                )
    return [
        FeatureEstimate(
            feature=name,
            calls=[
                estimate_call(
                    call, histories.get((call.task, call.per)), current_model(config, ctx, call)
                )
                for call in feature.calls
            ],
        )
        for name, feature in catalog.features.items()
    ]
