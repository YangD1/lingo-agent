"""Reviewing writing off the request path (Q38c).

`/writing` submits and polls the submission's status, since a long text can take tens
of seconds; writing_coach submits and `wait`s, as its turn needs the result. Like the
practice worker, a single backend process runs this with no queue: a submission still
`pending` at startup was cut off by a restart and is marked failed.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable

from langchain_core.runnables import RunnableConfig
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.exercise.worker import structured_call
from app.agents.exercise_graph import StructuredCall
from app.db.models import WritingSubmission
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context
from app.writing import service
from app.writing.review import TASK

logger = logging.getLogger(__name__)

# Builds the review call for a tenant; tests pass a fake.
type CallFactory = Callable[[TenantProviderContext, RunnableConfig], StructuredCall]


def review_call(ctx: TenantProviderContext, config: RunnableConfig) -> StructuredCall:
    return structured_call(ctx, config, TASK)


class WritingWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        calls: CallFactory = review_call,
        concurrency: int = 2,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._calls = calls
        self._slots = asyncio.Semaphore(concurrency)
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def submit(self, submission_id: int, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Review this committed, pending submission in the background."""
        if submission_id in self._tasks:
            return
        self._tasks[submission_id] = asyncio.create_task(
            self._run(submission_id, user_id, tenant_id), name=f"writing-{submission_id}"
        )

    async def wait(self, submission_id: int, at_most: float | None = None) -> None:
        """Until this submission's review has finished here, however it ended, or
        `at_most` seconds have passed; the review itself is never cancelled."""
        task = self._tasks.get(submission_id)
        if task is not None:
            await asyncio.wait({task}, timeout=at_most)

    async def recover(self) -> int:
        """At startup: submissions left pending by the last process never finish."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                update(WritingSubmission)
                .where(WritingSubmission.status == "pending")
                .values(status="failed", error_code="interrupted")
                .returning(WritingSubmission.id)
            )
            count = len(result.all())
            await session.commit()
        return count

    async def wait_idle(self) -> None:
        """Wait for all running reviews (tests; shutdown uses `stop`)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()

    async def _run(self, submission_id: int, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        try:
            async with self._slots:
                async with self._sessionmaker() as session:
                    ctx = await load_provider_context(session, tenant_id)
                # llm_usage attributes the call to this learner.
                config: RunnableConfig = {
                    "metadata": {"user_id": str(user_id)},
                    "tags": ["writing"],
                }
                await service.review(self._sessionmaker, submission_id, self._calls(ctx, config))
        except NoModelConfiguredError as exc:
            await service.fail(self._sessionmaker, submission_id, exc.code)
        except Exception:
            logger.exception("writing review %s failed", submission_id)
            await service.fail(self._sessionmaker, submission_id, "review_failed")
        except asyncio.CancelledError:
            await asyncio.shield(service.fail(self._sessionmaker, submission_id, "interrupted"))
            raise
        finally:
            self._tasks.pop(submission_id, None)
