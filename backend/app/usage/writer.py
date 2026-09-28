"""Background, batched inserts of usage records so model calls never wait on the DB."""

import asyncio
import dataclasses
import logging
from typing import Final

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LLMUsage
from app.usage.recorder import UsageRecord

logger = logging.getLogger(__name__)

_STOP: Final = object()


class UsageWriter:
    """Collects records from `submit` and inserts them in batches.

    A batch is written when it reaches `batch_size` or `flush_interval` seconds after
    its first record. When the queue is full new records are dropped (and counted):
    losing a usage row is better than slowing down or failing a reply.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        batch_size: int = 50,
        flush_interval: float = 2.0,
        max_queue: int = 10_000,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._queue: asyncio.Queue[UsageRecord | object] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0

    def submit(self, record: UsageRecord) -> None:
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 1000 == 0:
                logger.warning("usage queue full; %d records dropped so far", self.dropped)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="usage-writer")

    async def stop(self) -> None:
        """Write everything still queued, then stop the background task.

        Callers bound the wait themselves (`async with asyncio.timeout(...)`).
        """
        if self._task is None:
            return
        task, self._task = self._task, None
        try:
            await self._queue.put(_STOP)
            await task
        finally:
            task.cancel()

    async def flush(self) -> None:
        """Write whatever is queued right now (tests; the loop does this on its own)."""
        batch: list[UsageRecord] = []
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if isinstance(item, UsageRecord):
                batch.append(item)
        await self._write(batch)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            first = await self._queue.get()
            if first is _STOP:
                return
            batch = [first]
            deadline = loop.time() + self._flush_interval
            stopping = False
            while len(batch) < self._batch_size:
                try:
                    item = await asyncio.wait_for(self._queue.get(), deadline - loop.time())
                except TimeoutError:
                    break
                if item is _STOP:
                    stopping = True
                    break
                batch.append(item)
            await self._write([r for r in batch if isinstance(r, UsageRecord)])
            if stopping:
                return

    async def _write(self, batch: list[UsageRecord]) -> None:
        if not batch:
            return
        try:
            async with self._sessionmaker() as session:
                await session.execute(insert(LLMUsage), [dataclasses.asdict(r) for r in batch])
                await session.commit()
        except Exception:  # keep the loop alive; a DB outage only loses usage rows
            logger.exception("failed to write %d usage records", len(batch))
