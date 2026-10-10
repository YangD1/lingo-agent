"""Running word pronunciation jobs in the background (ADR 0028 §4, task 55).

A job runs batch after batch in a task of its own until it is done, paused or
cancelled. Progress is saved after every word, so unlike the other workers a job cut
off by a restart is not failed: `recover` picks up every job still `running`. Like
them, a single backend process runs this.

The route is loaded again before each batch, so a connection or voice changed in the
settings takes effect (or pauses the job, when its model left the route). These calls
are counted as background usage but not against the daily background budget (Q7): the
deployment confirmed this spending itself, and read-aloud has no tokens anyway.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WordAudioJob
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context
from app.providers.tts import TextToSpeech, get_tts
from app.services.speech import word_audio
from app.services.speech.word_audio import Sleep
from app.services.vocab.books import get_book

logger = logging.getLogger(__name__)

# Builds the tenant's read-aloud route; tests pass a fake.
type RouteFactory = Callable[[TenantProviderContext], TextToSpeech]


class WordAudioWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        route: RouteFactory = get_tts,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._route = route
        self._sleep = sleep
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def submit(self, job_id: uuid.UUID) -> None:
        """Run this committed, running job in the background (again after a resume)."""
        if job_id in self._tasks:
            return
        self._tasks[job_id] = asyncio.create_task(self._run(job_id), name=f"word-audio-{job_id}")

    async def recover(self) -> int:
        """At startup: carry on with the jobs the last process was running."""
        async with self._sessionmaker() as session:
            job_ids = list(
                await session.scalars(
                    select(WordAudioJob.id).where(WordAudioJob.status == "running")
                )
            )
        for job_id in job_ids:
            self.submit(job_id)
        return len(job_ids)

    async def wait_idle(self) -> None:
        """Wait for all running jobs (tests; shutdown uses `stop`)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        # Jobs stay `running`: the next start carries on from their cursor.
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()

    async def _run(self, job_id: uuid.UUID) -> None:
        try:
            while await self._batch(job_id):
                pass
        except Exception:
            logger.exception("word audio job %s failed", job_id)
            async with self._sessionmaker() as session:
                await word_audio.pause(session, job_id, "unexpected error, see the server log")
        finally:
            self._tasks.pop(job_id, None)

    async def _batch(self, job_id: uuid.UUID) -> bool:
        async with self._sessionmaker() as session:
            job = await session.get(WordAudioJob, job_id)
            if job is None or job.status != "running":
                return False
            book = get_book(job.book_id)
            if book is None:
                await word_audio.pause(session, job_id, f"unknown word book {job.book_id}")
                return False
            ctx = await load_provider_context(session, job.tenant_id)
            try:
                route = self._route(ctx)
            except NoModelConfiguredError:
                await word_audio.pause(session, job_id, "no read-aloud route configured")
                return False
            return await word_audio.run_batch(session, job_id, route, book, sleep=self._sleep)
