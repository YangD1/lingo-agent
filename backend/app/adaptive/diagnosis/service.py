"""One diagnosis of one learner (P2 plan §6.2): checks, the call, the row and the memory.

Whether a learner is due one is the triggers' business (`triggers.py`); this runs it.
The call is background work (ADR 0025): it needs the learner's switch on and the
tenant's daily budget left, and is recorded as background usage.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from langchain_core.runnables import RunnableConfig
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.diagnosis.checks import TASK, RootCause, diagnose
from app.adaptive.diagnosis.context import Language, load_context
from app.adaptive.exercise.worker import structured_call
from app.adaptive.kc.catalog import GrammarCatalog
from app.adaptive.rules import Rules
from app.agents.exercise_graph import StructuredCall
from app.db.models import Diagnosis, KCEvidence
from app.memory.service import MAX_CONTENT_LENGTH, add_memory, get_profile, update_memory
from app.providers.config import TenantProviderContext
from app.providers.tenant import load_provider_context
from app.scheduler import budget, prefs

type Trigger = Literal["weekly", "after_set"]
type Skip = Literal["disabled", "budget_exhausted", "nothing_to_diagnose"]
type CallFactory = Callable[[TenantProviderContext, RunnableConfig, str], StructuredCall]

# Starts the memory a diagnosis leaves (Q46d), so the learner can tell it apart.
MEMORY_PREFIX: dict[Language, str] = {
    "zh": "私教的诊断：",  # noqa: RUF001 (Chinese punctuation)
    "en": "Tutor's diagnosis: ",
}


@dataclass(frozen=True, slots=True)
class Outcome:
    # The new row; None when the run was skipped before calling the model.
    diagnosis_id: uuid.UUID | None = None
    skipped: Skip | None = None


async def run_diagnosis(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    trigger: Trigger,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime,
    calls: CallFactory | None = None,
) -> Outcome:
    """Diagnose the learner unless switched off, out of budget or with nothing to look
    at. Raises NoModelConfiguredError or the provider's error from the call."""
    async with sessionmaker() as session:
        if not await prefs.is_enabled(session, user_id, prefs.DIAGNOSIS):
            return Outcome(skipped="disabled")
        if (await budget.load(session, tenant_id, now)).exhausted:
            return Outcome(skipped="budget_exhausted")
        context = await load_context(session, user_id, rules=rules, catalog=catalog, now=now)
        # load_context may have rebuilt stale mastery rows.
        await session.commit()
        if context is None:
            return Outcome(skipped="nothing_to_diagnose")
        profile = await get_profile(session, user_id)
        language: Language = "en" if profile and profile.explanation_language == "en" else "zh"
        evidence_upto = await session.scalar(
            select(func.max(KCEvidence.id)).where(KCEvidence.user_id == user_id)
        )
        ctx = await load_provider_context(session, tenant_id)

    config: RunnableConfig = {"metadata": {"user_id": str(user_id), "background": True}}
    call = (calls or structured_call)(ctx, config, TASK)
    causes, model = await diagnose(call, context, language, rules)

    async with sessionmaker() as session:
        memory_id = await _remember(session, user_id, tenant_id, causes, language)
        # The id is set here: after the commit the row's attributes are expired.
        diagnosis_id = uuid.uuid4()
        session.add(
            Diagnosis(
                id=diagnosis_id,
                user_id=user_id,
                trigger=trigger,
                target_kc_ids=context.targets,
                root_causes=[cause.as_json() for cause in causes],
                language=language,
                evidence_upto=evidence_upto,
                model=model,
                rules_version=rules.version,
                memory_id=memory_id,
                created_at=now,
            )
        )
        await session.commit()
        return Outcome(diagnosis_id=diagnosis_id)


async def _remember(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    causes: list[RootCause],
    language: Language,
) -> uuid.UUID | None:
    """The fact memory of the most likely cause (Q46d): the last diagnosis' memory,
    updated in place while the learner keeps it, else a new one. Without a cause the
    last one is left as it is. Commits when it writes."""
    if not causes:
        return None
    content = (MEMORY_PREFIX[language] + causes[0].hypothesis)[:MAX_CONTENT_LENGTH]
    # A deleted memory leaves memory_id NULL on every diagnosis that pointed to it.
    last = await session.scalar(
        select(Diagnosis.memory_id)
        .where(Diagnosis.user_id == user_id, Diagnosis.memory_id.is_not(None))
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    if last is not None:
        return (await update_memory(session, user_id, last, content)).id
    memory = await add_memory(
        session, tenant_id=tenant_id, user_id=user_id, kind="fact", content=content
    )
    return memory.id
