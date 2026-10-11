"""A realtime call's row (ADR 0030 §6): opened once the vendor accepted the session,
its duration written as it goes, its transcript saved a reply at a time, ended at
hangup. Calls cut off by a restart are ended at startup with the duration last written.

An ended call stays `active` until its summary is made (`after.py`). Its whole length
counts as speaking time for the daily plan (Q61h): `spoken_seconds` follows
`call_seconds`; every learner line is a spoken turn."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.chat_graph import SPEAKING_COACH_NODE, ChatGraph
from app.chat.service import thread_config
from app.db.models import Conversation, SpeakingSession
from app.realtime.transcript import Line

logger = logging.getLogger(__name__)


async def save_progress(
    maker: async_sessionmaker[AsyncSession], session_id: uuid.UUID, seconds: float
) -> None:
    async with maker() as session:
        await session.execute(
            update(SpeakingSession)
            .where(SpeakingSession.id == session_id)
            .values(call_seconds=max(0.0, seconds), spoken_seconds=max(0.0, seconds))
        )
        await session.commit()


async def save_lines(
    maker: async_sessionmaker[AsyncSession],
    graph: ChatGraph,
    conversation_id: uuid.UUID,
    lines: list[Line],
) -> None:
    """Append finished lines to the call's conversation (Q61e). The graph never runs
    on it (nobody types into a call), so the update stands as the thread's state."""
    if not lines:
        return
    await graph.aupdate_state(
        thread_config(conversation_id),
        {"messages": [line.message() for line in lines]},
        as_node=SPEAKING_COACH_NODE,
    )
    learner = sum(1 for line in lines if line.role == "learner")
    async with maker() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        if learner:
            await session.execute(
                update(SpeakingSession)
                .where(SpeakingSession.conversation_id == conversation_id)
                .values(
                    turns=SpeakingSession.turns + learner,
                    spoken_turns=SpeakingSession.spoken_turns + learner,
                )
            )
        await session.commit()


async def finish(
    maker: async_sessionmaker[AsyncSession], session_id: uuid.UUID, seconds: float
) -> None:
    """The call hung up; what follows is `after.py`'s."""
    seconds = max(0.0, seconds)
    async with maker() as session:
        await session.execute(
            update(SpeakingSession)
            .where(SpeakingSession.id == session_id, SpeakingSession.ended_at.is_(None))
            .values(call_seconds=seconds, spoken_seconds=seconds, ended_at=datetime.now(UTC))
        )
        await session.commit()


async def close_orphaned(maker: async_sessionmaker[AsyncSession]) -> int:
    """At startup: calls never ended were cut off by the last shutdown. Their summary
    comes from `AfterCall.recover`."""
    async with maker() as session:
        result = await session.execute(
            update(SpeakingSession)
            .where(
                SpeakingSession.mode == "realtime",
                SpeakingSession.status == "active",
                SpeakingSession.ended_at.is_(None),
            )
            .values(ended_at=datetime.now(UTC))
        )
        await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


class Stoppable(Protocol):
    @property
    def user_id(self) -> uuid.UUID: ...

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

    def has_user(self, user_id: uuid.UUID) -> bool:
        return any(call.user_id == user_id for call in self._calls)

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
