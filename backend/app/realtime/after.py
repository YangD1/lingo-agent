"""After a realtime call hangs up (ADR 0030 §6, Q61g, Q61i).

The call's transcript is already in its conversation (`transcript.py`). Two things
follow, off the request path:

- reflection, as after any conversation: memories, grammar tags (source `speaking`,
  short turns give no mistakes, ADR 0029 §4) and collected words;
- the speaking summary and the move in speaking ability, like a cascade session's
  ending (`speaking.sessions.summarize`). Only when the learner said something and the
  call lasted at least `MIN_SUMMARY_SECONDS` (Q61g); otherwise no model is called.

A call stays `active`, with `ended_at` set, until its summary is made: a restart picks
it up again (`recover`). A summary that fails leaves it `failed`; ending it through
the API retries.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.chat_graph import ChatGraph
from app.chat.locks import ConversationLocks
from app.db.models import Conversation, SpeakingSession
from app.memory.worker import DEFAULT_LANGUAGE, ReflectionWorker
from app.providers.errors import NoModelConfiguredError
from app.speaking import sessions

logger = logging.getLogger(__name__)

# Shorter calls get no summary (Q61g): too little to sum up.
MIN_SUMMARY_SECONDS = 30.0


class AfterCall:
    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        graph: ChatGraph,
        reflection: ReflectionWorker,
        locks: ConversationLocks,
    ) -> None:
        self._maker = maker
        self._graph = graph
        self._reflection = reflection
        self._locks = locks
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def schedule(self, session_id: uuid.UUID, *, language: str = DEFAULT_LANGUAGE) -> None:
        if session_id in self._tasks:
            return
        task = asyncio.create_task(self._run(session_id, language), name=f"after-{session_id}")
        self._tasks[session_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(session_id, None))

    async def recover(self) -> int:
        """At startup: hung-up calls still waiting for their summary."""
        async with self._maker() as session:
            ids = list(
                await session.scalars(
                    select(SpeakingSession.id).where(
                        SpeakingSession.mode == "realtime",
                        SpeakingSession.status == "active",
                        SpeakingSession.ended_at.is_not(None),
                    )
                )
            )
        for session_id in ids:
            self.schedule(session_id)
        return len(ids)

    async def wait_idle(self) -> None:
        """Wait for all scheduled work (tests)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def _run(self, session_id: uuid.UUID, language: str) -> None:
        try:
            await self._follow_up(session_id, language)
        except Exception:
            logger.exception("after realtime call %s", session_id)

    async def _follow_up(self, session_id: uuid.UUID, language: str) -> None:
        async with self._maker() as session:
            row = await session.get(SpeakingSession, session_id)
            if row is None or row.mode != "realtime" or row.ended_at is None:
                return
            if row.status != "active":
                return
            conversation_id, seconds = row.conversation_id, row.call_seconds
            tenant_id = await session.scalar(
                select(Conversation.tenant_id).where(Conversation.id == conversation_id)
            )
        if tenant_id is None:
            return
        self._reflection.schedule(conversation_id, finish=True, language=language)
        if seconds < MIN_SUMMARY_SECONDS:
            await self._close(session_id, "done")
            return
        try:
            # None: the API is ending it right now.
            await sessions.summarize(
                self._maker, self._graph, self._locks, tenant_id, session_id, conversation_id
            )
        except NoModelConfiguredError:
            # No chat model to sum up with: ending it again once there is one retries.
            await self._close(session_id, "failed")

    async def _close(self, session_id: uuid.UUID, status: str) -> None:
        async with self._maker() as session:
            await session.execute(
                update(SpeakingSession)
                .where(SpeakingSession.id == session_id, SpeakingSession.status == "active")
                .values(status=status)
            )
            await session.commit()
