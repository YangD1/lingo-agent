"""A realtime call's row (ADR 0030 §6): opened once the vendor accepted the session,
its duration written as it goes, closed at hangup. Calls cut off by a restart are
closed at startup with the duration last written."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import SpeakingSession

logger = logging.getLogger(__name__)


async def save_progress(
    maker: async_sessionmaker[AsyncSession], session_id: uuid.UUID, seconds: float
) -> None:
    async with maker() as session:
        await session.execute(
            update(SpeakingSession)
            .where(SpeakingSession.id == session_id)
            .values(call_seconds=max(0.0, seconds))
        )
        await session.commit()


async def finish(
    maker: async_sessionmaker[AsyncSession], session_id: uuid.UUID, seconds: float
) -> None:
    """The call hung up. Transcripts, reflection and the summary come with task 61."""
    async with maker() as session:
        await session.execute(
            update(SpeakingSession)
            .where(SpeakingSession.id == session_id, SpeakingSession.status == "active")
            .values(call_seconds=max(0.0, seconds), status="done", ended_at=datetime.now(UTC))
        )
        await session.commit()


async def close_orphaned(maker: async_sessionmaker[AsyncSession]) -> int:
    """At startup: calls still `active` were cut off by the last shutdown."""
    async with maker() as session:
        result = await session.execute(
            update(SpeakingSession)
            .where(SpeakingSession.mode == "realtime", SpeakingSession.status == "active")
            .values(status="done", ended_at=datetime.now(UTC))
        )
        await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


class Stoppable(Protocol):
    def stop(self, reason: str) -> None: ...


class RealtimeCalls:
    """The calls in progress, so shutdown can end them cleanly (ADR 0030 §1): the
    browser is told why, and each call's row is closed."""

    def __init__(self) -> None:
        self._calls: dict[Stoppable, asyncio.Event] = {}

    def add(self, call: Stoppable) -> None:
        self._calls[call] = asyncio.Event()

    def done(self, call: Stoppable) -> None:
        event = self._calls.pop(call, None)
        if event is not None:
            event.set()

    def __len__(self) -> int:
        return len(self._calls)

    async def stop_all(self, timeout: float = 5.0) -> None:  # noqa: ASYNC109
        waits = [event.wait() for event in self._calls.values()]
        for call in list(self._calls):
            call.stop("server_stopping")
        if not waits:
            return
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*waits)
        except TimeoutError:
            logger.warning("%d realtime calls did not end within %ss", len(self._calls), timeout)
