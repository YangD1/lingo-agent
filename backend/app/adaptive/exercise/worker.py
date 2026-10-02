"""Generating practice sets off the request path (ADR 0021 §4, Q33e).

`start` hands the learner a set at once: one generated ahead of time if there is a
fresh one, one already being generated, or a new `generating` row whose items the
graph writes in a task while the page shows its progress (`stage`). `prefetch`, called
when a set is done, writes the next one in the background; each learner has at most
one such set waiting. A set generated ahead of time is used only while younger than
`practice.prefetch_max_hours` and planned under the current rules; otherwise it is
marked failed (`expired`) and a new one is generated.

Like the reflection worker, a single backend process runs this: there is no queue, and
a set still `generating` at startup was cut off by a restart and is marked failed.
"""

import asyncio
import logging
import secrets
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.exercise import bank, inputs, service
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.agents.exercise_graph import (
    ExerciseContext,
    ExerciseGraph,
    ModelReply,
    SetResult,
    Stage,
    StructuredCall,
    start_state,
)
from app.db.models import ExerciseSet
from app.providers.config import TenantProviderContext
from app.providers.llm import get_structured_llm
from app.providers.tenant import load_provider_context

logger = logging.getLogger(__name__)

GENERATE_TASK = "exercise_generate"
CRITIC_TASK = "exercise_critic"

# Builds the two model calls for a tenant; tests pass fakes.
type CallFactory = Callable[
    [TenantProviderContext, RunnableConfig], tuple[StructuredCall, StructuredCall]
]


class _AnsweredBy(BaseCallbackHandler):
    """Notes which model of a fallback chain produced the last successful answer."""

    run_inline = True

    def __init__(self) -> None:
        self._started: dict[uuid.UUID, str] = {}
        self.model: str | None = None

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: uuid.UUID,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        connection = next(
            (t.removeprefix("connection:") for t in tags or [] if t.startswith("connection:")),
            None,
        )
        name = (metadata or {}).get("ls_model_name")
        if connection and name:
            self._started[run_id] = f"{connection}:{name}"

    def on_llm_end(self, response: LLMResult, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        if run_id in self._started:
            self.model = self._started.pop(run_id)


def model_calls(
    ctx: TenantProviderContext, config: RunnableConfig
) -> tuple[StructuredCall, StructuredCall]:
    def call(task: str) -> StructuredCall:
        async def invoke(messages: Sequence[BaseMessage], schema: type[BaseModel]) -> ModelReply:
            answered = _AnsweredBy()
            run: RunnableConfig = {
                **config,
                "callbacks": [answered],
                "tags": [*config.get("tags", []), task],
            }
            output = await get_structured_llm(ctx, task, schema).ainvoke(messages, config=run)
            return ModelReply(output, answered.model)

        return invoke

    return call(GENERATE_TASK), call(CRITIC_TASK)


class PracticeWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        graph: ExerciseGraph,
        *,
        calls: CallFactory = model_calls,
        prefetch_enabled: bool = True,
        concurrency: int = 2,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessionmaker = sessionmaker
        self._graph = graph
        self._calls = calls
        self.prefetch_enabled = prefetch_enabled
        self._slots = asyncio.Semaphore(concurrency)
        self._clock = clock
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._stages: dict[uuid.UUID, Stage] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def stage(self, set_id: uuid.UUID) -> Stage | None:
        """How far generation of this set has got; None when it is not running here."""
        return self._stages.get(set_id)

    async def start(self, user_id: uuid.UUID, tenant_id: uuid.UUID, origin: str) -> uuid.UUID:
        """The set the learner practises next; see the module docstring."""
        async with self._lock(user_id), self._sessionmaker() as session:
            await self._expire(session, user_id)
            waiting = await self._waiting(session, user_id)
            if waiting is not None:
                waiting.started_at = waiting.started_at or self._clock()
                await session.commit()
                return waiting.id
            set_id = await self._create(session, user_id, origin, started=True)
        self._spawn(set_id, user_id, tenant_id)
        return set_id

    async def prefetch(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> uuid.UUID | None:
        """Generate the learner's next set in the background, unless one is waiting."""
        if not self.prefetch_enabled:
            return None
        async with self._lock(user_id), self._sessionmaker() as session:
            await self._expire(session, user_id)
            if await self._waiting(session, user_id) is not None:
                await session.commit()
                return None
            set_id = await self._create(session, user_id, "prefetch", started=False)
        self._spawn(set_id, user_id, tenant_id)
        return set_id

    async def recover(self) -> int:
        """At startup: sets left `generating` by the last process never finish."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                update(ExerciseSet)
                .where(ExerciseSet.status == "generating")
                .values(status="failed", error_code="interrupted")
                .returning(ExerciseSet.id)
            )
            count = len(result.all())
            await session.commit()
        return count

    async def wait_idle(self) -> None:
        """Wait for all running generation (tests; shutdown uses `stop`)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()

    # --- internals ---

    def _lock(self, user_id: uuid.UUID) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def _expire(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        """Retire sets generated ahead of time that are too old or under old rules."""
        rules = get_rules()
        oldest = self._clock() - timedelta(hours=rules.practice.prefetch_max_hours)
        await session.execute(
            update(ExerciseSet)
            .where(
                ExerciseSet.user_id == user_id,
                ExerciseSet.status == "ready",
                ExerciseSet.started_at.is_(None),
                or_(ExerciseSet.created_at < oldest, ExerciseSet.rules_version != rules.version),
            )
            .values(status="failed", error_code="expired")
        )

    async def _waiting(self, session: AsyncSession, user_id: uuid.UUID) -> ExerciseSet | None:
        """A set still being generated (started or not), or a ready one nobody started."""
        return await session.scalar(
            select(ExerciseSet)
            .where(
                ExerciseSet.user_id == user_id,
                or_(
                    ExerciseSet.status == "generating",
                    (ExerciseSet.status == "ready") & ExerciseSet.started_at.is_(None),
                ),
            )
            .order_by(ExerciseSet.created_at.desc())
            .limit(1)
        )

    async def _create(
        self, session: AsyncSession, user_id: uuid.UUID, origin: str, *, started: bool
    ) -> uuid.UUID:
        row = ExerciseSet(
            user_id=user_id,
            origin=origin,
            status="generating",
            kc_plan=[],
            rules_version=get_rules().version,
            started_at=self._clock() if started else None,
        )
        session.add(row)
        await session.commit()
        return row.id

    def _spawn(self, set_id: uuid.UUID, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self._stages[set_id] = "generating"
        self._tasks[set_id] = asyncio.create_task(
            self._run(set_id, user_id, tenant_id), name=f"practice-{set_id}"
        )

    async def _run(self, set_id: uuid.UUID, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        try:
            async with self._slots:
                await self._generate(set_id, user_id, tenant_id)
        except Exception:
            logger.exception("practice set %s failed", set_id)
            await self._fail(set_id, "generation_failed")
        except asyncio.CancelledError:
            await asyncio.shield(self._fail(set_id, "interrupted"))
            raise
        finally:
            self._tasks.pop(set_id, None)
            self._stages.pop(set_id, None)

    async def _fail(self, set_id: uuid.UUID, code: str) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(ExerciseSet)
                .where(ExerciseSet.id == set_id, ExerciseSet.status == "generating")
                .values(status="failed", error_code=code)
            )
            await session.commit()

    async def _generate(self, set_id: uuid.UUID, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        rules, catalog = get_rules(), get_grammar_catalog()
        now = self._clock()
        seed = secrets.randbits(31)
        async with self._sessionmaker() as session:
            learner = await inputs.load(session, user_id, rules=rules, catalog=catalog, now=now)
            planned = inputs.plan_set(learner, catalog=catalog, rules=rules, now=now, seed=seed)
            briefs = inputs.briefs(planned, learner, catalog)
            wider = inputs.wider_kcs(learner, catalog=catalog, rules=rules, now=now)
            item_bank = await bank.load_bank(session, rules)
            seen = await bank.seen_items(session, user_id)
            provider_ctx = await load_provider_context(session, tenant_id)
            await session.execute(
                update(ExerciseSet)
                .where(ExerciseSet.id == set_id)
                .values(kc_plan=[asdict(p) for p in planned], rules_version=rules.version)
            )
            await session.commit()
        # llm_usage attributes the calls to this learner.
        config: RunnableConfig = {"metadata": {"user_id": str(user_id)}, "tags": ["practice"]}
        generate, critique = self._calls(provider_ctx, config)

        async def save(result: SetResult) -> None:
            async with self._sessionmaker() as session:
                await service.save_result(session, user_id, set_id, result)
                await session.commit()

        async def report(stage: Stage) -> None:
            self._stages[set_id] = stage

        ctx = ExerciseContext(
            generate=generate,
            critique=critique,
            learner=learner,
            briefs=briefs,
            catalog=catalog,
            rules=rules,
            bank=item_bank,
            seen=seen,
            now=now,
            seed=seed,
            save=save,
            report=report,
            wider_kcs=wider,
        )
        await self._graph.ainvoke(start_state(briefs, rules), context=ctx)
