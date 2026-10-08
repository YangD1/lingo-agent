"""Writing graded versions of articles off the request path (Q42f, Q42g).

`request` hands a learner the version of an article at their level: the cached one, or
a new `generating` row whose text the graph writes in a task while the page shows its
progress (`stage`). A failed version is generated again when asked for. The unique
(tenant, article, level) row makes sure two learners opening the same article at once
start only one rewrite. `generate` is the background job's way in (Q42g): it writes a
version and waits for it, so the job can check the budget between articles.

Like the practice worker, a single backend process runs this: a version still
`generating` at startup was cut off by a restart and is marked failed.
"""

import asyncio
import logging
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.exercise.worker import structured_call
from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import get_rules
from app.agents.exercise_graph import StructuredCall
from app.agents.reading_graph import (
    ReadingContext,
    ReadingGraph,
    RewriteResult,
    Stage,
    start_state,
)
from app.db.models import ArticleVersion
from app.providers.config import TenantProviderContext
from app.providers.tenant import load_provider_context
from app.services.news import feeds
from app.services.reading import messages, versions

logger = logging.getLogger(__name__)

REWRITE_TASK = "article_rewrite"
# Recorded under their own names in llm_usage, routed like these (features.yaml).
QUESTIONS_TASK = "reading_questions"
CRITIC_TASK = "reading_critic"
CRITIC_ROUTE = "exercise_critic"

# Builds the three model calls for a tenant; tests pass fakes.
type CallFactory = Callable[
    [TenantProviderContext, RunnableConfig], tuple[StructuredCall, StructuredCall, StructuredCall]
]


def _as(config: RunnableConfig, usage_task: str) -> RunnableConfig:
    return {**config, "metadata": {**config.get("metadata", {}), "usage_task": usage_task}}


def model_calls(
    ctx: TenantProviderContext, config: RunnableConfig
) -> tuple[StructuredCall, StructuredCall, StructuredCall]:
    return (
        structured_call(ctx, config, REWRITE_TASK),
        structured_call(ctx, _as(config, QUESTIONS_TASK), REWRITE_TASK),
        structured_call(ctx, _as(config, CRITIC_TASK), CRITIC_ROUTE),
    )


class ReadingWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        graph: ReadingGraph,
        *,
        calls: CallFactory = model_calls,
        concurrency: int = 2,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessionmaker = sessionmaker
        self._graph = graph
        self._calls = calls
        self._slots = asyncio.Semaphore(concurrency)
        self._clock = clock
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._stages: dict[uuid.UUID, Stage] = {}

    def stage(self, version_id: uuid.UUID) -> Stage | None:
        """How far the rewrite has got; None when it is not running here."""
        return self._stages.get(version_id)

    async def request(self, user_id: uuid.UUID, tenant_id: uuid.UUID, article_id: int) -> uuid.UUID:
        """The version of the article at the learner's level, started if needed.
        Raises `FeedError` for an article the learner cannot see, `ReadingError` for
        one that is not rewritten for them."""
        rules = get_rules()
        async with self._sessionmaker() as session:
            view = await feeds.get_article(session, article_id, tenant_id)
            level = await versions.reading_level(session, user_id, rules)
            versions.check_rewritable(view.article, level, rules)
            version_id, start = await self._claim(
                session, tenant_id, article_id, level, background=False
            )
        if start:
            self._stages[version_id] = "rewriting"
            self._tasks[version_id] = asyncio.create_task(
                self._run(version_id, tenant_id, user_id, background=False),
                name=f"reading-{version_id}",
            )
        return version_id

    async def generate(
        self, tenant_id: uuid.UUID, article_id: int, level: CefrLevel
    ) -> uuid.UUID | None:
        """Write the version in the background job and wait for it (Q42g); None when
        it exists already or is being written."""
        async with self._sessionmaker() as session:
            version_id, start = await self._claim(
                session, tenant_id, article_id, level, background=True
            )
        if not start:
            return None
        self._stages[version_id] = "rewriting"
        await self._run(version_id, tenant_id, None, background=True)
        return version_id

    async def recover(self) -> int:
        """At startup: versions left `generating` by the last process never finish."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                update(ArticleVersion)
                .where(ArticleVersion.status == "generating")
                .values(status="failed", error_code="interrupted")
                .returning(ArticleVersion.id)
            )
            count = len(result.all())
            await session.commit()
        return count

    async def wait_idle(self) -> None:
        """Wait for all running rewrites (tests; shutdown uses `stop`)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()

    # --- internals ---

    async def _claim(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        article_id: int,
        level: CefrLevel,
        *,
        background: bool,
    ) -> tuple[uuid.UUID, bool]:
        """The version's id, and whether the caller is to write it: true for a new row
        or a failed one taken back to `generating`; commits."""
        new_id = await session.scalar(
            insert(ArticleVersion)
            .values(
                tenant_id=tenant_id,
                article_id=article_id,
                level=level,
                status="generating",
                background=background,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "article_id", "level"])
            .returning(ArticleVersion.id)
        )
        if new_id is not None:
            await session.commit()
            return new_id, True
        existing = await session.scalar(
            select(ArticleVersion).where(
                ArticleVersion.tenant_id == tenant_id,
                ArticleVersion.article_id == article_id,
                ArticleVersion.level == level,
            )
        )
        assert existing is not None
        if existing.status != "failed":
            await session.commit()
            return existing.id, False
        retried = await session.scalar(
            update(ArticleVersion)
            .where(ArticleVersion.id == existing.id, ArticleVersion.status == "failed")
            .values(
                status="generating",
                error_code=None,
                background=background,
                created_at=self._clock(),
                finished_at=None,
            )
            .returning(ArticleVersion.id)
        )
        await session.commit()
        return existing.id, retried is not None

    async def _run(
        self,
        version_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        *,
        background: bool,
    ) -> None:
        try:
            async with self._slots:
                await self._generate(version_id, tenant_id, user_id, background)
        except Exception:
            logger.exception("article version %s failed", version_id)
            await self._fail(version_id, "generation_failed")
        except asyncio.CancelledError:
            await asyncio.shield(self._fail(version_id, "interrupted"))
            raise
        finally:
            self._tasks.pop(version_id, None)
            self._stages.pop(version_id, None)

    async def _fail(self, version_id: uuid.UUID, code: str) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(ArticleVersion)
                .where(ArticleVersion.id == version_id, ArticleVersion.status == "generating")
                .values(status="failed", error_code=code, finished_at=self._clock())
            )
            await session.commit()

    async def _generate(
        self,
        version_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        background: bool,
    ) -> None:
        rules = get_rules()
        async with self._sessionmaker() as session:
            source, level = await versions.load_source(session, version_id)
            provider_ctx = await load_provider_context(session, tenant_id)
        # llm_usage attributes an on-demand rewrite to the learner who opened the
        # article; the background job's count against the tenant's daily budget.
        metadata: dict[str, object] = {"background": background}
        if user_id is not None:
            metadata["user_id"] = str(user_id)
        config: RunnableConfig = {"metadata": metadata, "tags": ["reading"]}
        rewrite, questions, critique = self._calls(provider_ctx, config)

        async def save(result: RewriteResult) -> None:
            async with self._sessionmaker() as session:
                await versions.save_result(
                    session, version_id, result, level=level, rules=rules, now=self._clock()
                )
                await session.commit()

        async def report(stage: Stage) -> None:
            self._stages[version_id] = stage

        ctx = ReadingContext(
            rewrite=rewrite,
            questions=questions,
            critique=critique,
            title=source.title,
            source=messages.source_paragraphs(source.body, rules.reading.max_source_words),
            level=level,
            rules=rules,
            seed=secrets.randbits(31),
            save=save,
            report=report,
        )
        await self._graph.ainvoke(start_state(rules), context=ctx)
