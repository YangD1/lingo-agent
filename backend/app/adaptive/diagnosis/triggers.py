"""When a learner is diagnosed (Q46b).

- Weekly: a daily job diagnoses learners whose last diagnosis is `interval_days` old
  (or who never had one) and who made counted mistakes since.
- After a practice set: `DiagnosisWorker.after_set` diagnoses in the background when the
  last diagnosis is `after_set_min_hours` old and `after_set_min_mistakes` counted
  mistakes came since.

"Since" is by evidence id (`diagnoses.evidence_upto`), not by time.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.diagnosis.service import CallFactory, Trigger, run_diagnosis
from app.adaptive.exercise.inputs import counted_mistakes
from app.adaptive.kc.catalog import GrammarCatalog, get_grammar_catalog
from app.adaptive.rules import Rules, get_rules
from app.db.models import Diagnosis, TenantMember
from app.providers.errors import NoModelConfiguredError
from app.scheduler import budget

logger = logging.getLogger(__name__)


async def _last(session: AsyncSession, user_id: uuid.UUID) -> Diagnosis | None:
    return await session.scalar(
        select(Diagnosis)
        .where(Diagnosis.user_id == user_id)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )


async def _new_mistakes(
    session: AsyncSession,
    user_id: uuid.UUID,
    last: Diagnosis | None,
    *,
    rules: Rules,
    now: datetime,
) -> dict[str, int]:
    """Counted mistakes per KC within `mistake_days`, after the last diagnosis."""
    return await counted_mistakes(
        session,
        user_id,
        rules=rules,
        since=now - timedelta(days=rules.diagnosis.mistake_days),
        after_evidence=last.evidence_upto if last else None,
    )


async def due(
    session: AsyncSession, user_id: uuid.UUID, trigger: Trigger, *, rules: Rules, now: datetime
) -> bool:
    """Whether the learner is due a diagnosis of this kind. Cheap: a diagnosis that
    finds no KC to look at still makes no call (`run_diagnosis`)."""
    diagnosis = rules.diagnosis
    last = await _last(session, user_id)
    if trigger == "weekly":
        if last is not None and now - last.created_at < timedelta(days=diagnosis.interval_days):
            return False
        new = await _new_mistakes(session, user_id, last, rules=rules, now=now)
        return bool(new) and (last is not None or max(new.values()) >= diagnosis.min_mistakes)
    if last is not None and now - last.created_at < timedelta(hours=diagnosis.after_set_min_hours):
        return False
    new = await _new_mistakes(session, user_id, last, rules=rules, now=now)
    return sum(new.values()) >= diagnosis.after_set_min_mistakes


async def diagnose_due(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime,
    calls: CallFactory | None = None,
) -> str | None:
    """One run of the daily `diagnosis` job; returns `budget.EXHAUSTED` when every
    tenant with a learner due was out of budget before diagnosing anyone, else None.
    A tenant without a model, or whose provider fails, is left for the next run."""
    async with sessionmaker() as session:
        members = await session.execute(
            select(TenantMember.tenant_id, TenantMember.user_id).order_by(
                TenantMember.tenant_id, TenantMember.user_id
            )
        )
        by_tenant: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for tenant_id, user_id in members.all():
            by_tenant[tenant_id].append(user_id)
    done = 0
    out_of_budget = 0
    for tenant_id, learners in by_tenant.items():
        for user_id in learners:
            async with sessionmaker() as session:
                if not await due(session, user_id, "weekly", rules=rules, now=now):
                    continue
            try:
                outcome = await run_diagnosis(
                    sessionmaker,
                    user_id,
                    tenant_id,
                    "weekly",
                    rules=rules,
                    catalog=catalog,
                    now=now,
                    calls=calls,
                )
            except NoModelConfiguredError:
                logger.info("diagnosis: no model for tenant %s", tenant_id)
                break
            except Exception:
                # Details stay in the server log; vendor errors can echo input.
                logger.exception("diagnosis of %s failed", user_id)
                break
            if outcome.skipped == budget.EXHAUSTED:
                out_of_budget += 1
                break
            done += outcome.diagnosis_id is not None
    logger.info("diagnosis: %d learners diagnosed, %d tenants out of budget", done, out_of_budget)
    return budget.EXHAUSTED if out_of_budget and done == 0 else None


class DiagnosisWorker:
    """Diagnoses after a finished practice set, off the request path (Q46b)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        enabled: bool = True,
        calls: CallFactory | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessionmaker = sessionmaker
        # Off for the whole process (tests).
        self.enabled = enabled
        self._calls = calls
        self._clock = clock
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def after_set(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Diagnose in the background if the learner is due; at most one at a time."""
        if not self.enabled or user_id in self._tasks:
            return
        task = asyncio.create_task(self._after_set(user_id, tenant_id))
        self._tasks[user_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(user_id, None))

    async def _after_set(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        rules, now = get_rules(), self._clock()
        try:
            async with self._sessionmaker() as session:
                if not await due(session, user_id, "after_set", rules=rules, now=now):
                    return
            outcome = await run_diagnosis(
                self._sessionmaker,
                user_id,
                tenant_id,
                "after_set",
                rules=rules,
                catalog=get_grammar_catalog(),
                now=now,
                calls=self._calls,
            )
            if outcome.skipped:
                logger.info("diagnosis after a set skipped for %s: %s", user_id, outcome.skipped)
        except Exception:
            logger.exception("diagnosis after a set failed for %s", user_id)

    async def wait_idle(self) -> None:
        """Wait for running diagnoses (tests; shutdown uses `stop`)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()
