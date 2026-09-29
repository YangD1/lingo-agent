"""Runs reflection after replies, off the request path (ADR 0009 §3).

One task per conversation at a time: a turn finishing while that conversation is still
being reflected on just marks it for another pass. Progress is kept in the conversation
row (`reflected_message_id`, `summarized_message_id`), not in memory, so a restart only
delays work: the next pass picks up everything after the cursors. No task queue, like
the attachment processor: the backend runs a single worker process.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activity import service as activity
from app.activity.service import (
    ActivityStatus,
    GrammarMistake,
    GrammarTags,
    MemoryChanges,
    SummaryUpdate,
    timed,
)
from app.adaptive import mastery
from app.adaptive.evidence import ChatEvidence, record_chat_evidence
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.agents.chat_graph import ChatGraph
from app.chat.service import thread_config
from app.db.models import Conversation, Memory
from app.memory import reflection, service
from app.memory.embedding import memory_embedder
from app.memory.reflection import Applied, KnownFact
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context

logger = logging.getLogger(__name__)

# How many learner turns go into the conversation summary before it is rewritten.
SUMMARY_EVERY_TURNS = 6
# Messages reflected on when there is no cursor yet (a conversation from before
# reflection existed): the recent past only, not the whole history.
BACKLOG_MESSAGES = 6
# Earlier messages shown to the model for context (not reflected on again).
CONTEXT_MESSAGES = 4
# Facts shown to the model; beyond this it can still add but not edit the oldest.
FACTS_SHOWN = 60
RECOVER_WITHIN = timedelta(days=1)
DEFAULT_LANGUAGE = "English"


@dataclass
class _Job:
    language: str = DEFAULT_LANGUAGE
    # Summarize whatever is new, even under SUMMARY_EVERY_TURNS (the learner moved on).
    finish: bool = False


class ReflectionWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        graph: ChatGraph,
        *,
        enabled: bool = True,
        concurrency: int = 2,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._graph = graph
        self.enabled = enabled
        self._slots = asyncio.Semaphore(concurrency)
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._pending: dict[uuid.UUID, _Job] = {}

    def schedule(
        self, conversation_id: uuid.UUID, *, language: str = DEFAULT_LANGUAGE, finish: bool = False
    ) -> None:
        """Reflect on this conversation's new messages soon."""
        if not self.enabled:
            return
        job = self._pending.setdefault(conversation_id, _Job())
        job.language = language
        job.finish = job.finish or finish
        if conversation_id not in self._tasks:
            task = asyncio.create_task(
                self._drain(conversation_id), name=f"reflect-{conversation_id}"
            )
            self._tasks[conversation_id] = task

    async def finish_previous(
        self, user_id: uuid.UUID, *, except_conversation_id: uuid.UUID, language: str
    ) -> None:
        """The learner started a new conversation: summarize the one they left."""
        if not self.enabled:
            return
        async with self._sessionmaker() as session:
            previous = await session.scalar(
                select(Conversation.id)
                .where(Conversation.user_id == user_id, Conversation.id != except_conversation_id)
                .order_by(Conversation.updated_at.desc())
                .limit(1)
            )
        if previous is not None:
            self.schedule(previous, finish=True, language=language)

    async def recover(self) -> int:
        """At startup: revisit recently active conversations (cheap when up to date)."""
        if not self.enabled:
            return 0
        since = datetime.now(UTC) - RECOVER_WITHIN
        async with self._sessionmaker() as session:
            ids = list(
                await session.scalars(
                    select(Conversation.id).where(Conversation.updated_at >= since).limit(200)
                )
            )
        for conversation_id in ids:
            self.schedule(conversation_id)
        return len(ids)

    def is_busy(self, conversation_id: uuid.UUID) -> bool:
        """Reflection on this conversation is queued or running (the learner-facing
        activity of its latest turn may still be coming)."""
        return conversation_id in self._tasks or conversation_id in self._pending

    async def wait_idle(self) -> None:
        """Wait for all scheduled work (tests; shutdown uses `stop`)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()

    async def _drain(self, conversation_id: uuid.UUID) -> None:
        try:
            while (job := self._pending.pop(conversation_id, None)) is not None:
                async with self._slots:
                    try:
                        await self._run(conversation_id, job)
                    except Exception:
                        logger.exception("reflection failed for conversation %s", conversation_id)
        finally:
            self._tasks.pop(conversation_id, None)

    async def _run(self, conversation_id: uuid.UUID, job: _Job) -> None:
        async with self._sessionmaker() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                return  # deleted meanwhile
            ctx = await load_provider_context(session, conversation.tenant_id)
        state = await self._graph.aget_state(thread_config(conversation_id))
        messages = [m for m in state.values.get("messages", []) if m.type in ("human", "ai")]
        if not messages:
            return
        config: RunnableConfig = {
            # llm_usage attributes the calls to this learner and conversation.
            "metadata": {
                "user_id": str(conversation.user_id),
                "conversation_id": str(conversation_id),
            },
            "tags": ["reflect"],
        }
        await self._reflect(conversation, ctx, messages, job, config)
        await self._summarize(conversation, ctx, messages, job, config)

    async def _reflect(
        self,
        conversation: Conversation,
        ctx: TenantProviderContext,
        messages: Sequence[BaseMessage],
        job: _Job,
        config: RunnableConfig,
    ) -> None:
        new, earlier = split_after(messages, conversation.reflected_message_id, BACKLOG_MESSAGES)
        if not new:
            return
        async with self._sessionmaker() as session:
            rows = await service.list_memories(session, conversation.user_id, "fact")
            facts = [KnownFact(m.id, m.content) for m in rows[:FACTS_SHOWN]]
            profile = await service.get_profile(session, conversation.user_id)
        prompt = reflection.reflection_input(
            profile=profile,
            facts=facts,
            earlier=earlier[-CONTEXT_MESSAGES:],
            new=new,
            language=job.language,
        )
        applied: Applied | None = None
        items: list[ChatEvidence] = []
        status: ActivityStatus
        with timed() as watch:
            try:
                result = await _twice(lambda: reflection.reflect(ctx, prompt, config))
            except NoModelConfiguredError:
                result, status = None, "skipped"
            else:
                status = "ok" if result is not None else "failed"
            if result is not None:
                async with self._sessionmaker() as session:
                    applied = await reflection.apply_reflection(
                        session,
                        result,
                        tenant_id=conversation.tenant_id,
                        user_id=conversation.user_id,
                        conversation_id=conversation.id,
                        facts=facts,
                        embedder=memory_embedder(ctx),
                    )
                logger.info("reflected on conversation %s: %s", conversation.id, applied)
                items = await self._record_evidence(conversation, new, result)
        await self._record_reflection_activity(conversation, new, status, applied, items, watch.ms)
        # Advanced even when the model failed twice: a turn is not worth retrying forever.
        await self._move_cursor(conversation.id, reflected_message_id=new[-1].id)

    async def _record_evidence(
        self,
        conversation: Conversation,
        new: Sequence[BaseMessage],
        result: reflection.Reflection,
    ) -> list[ChatEvidence]:
        """Grammar evidence from the reflected messages, then the mastery it changes."""
        learner_ids = reflection.learner_message_ids(new)
        catalog, rules = get_grammar_catalog(), get_rules()
        items = reflection.tagged_evidence(result, learner_ids, catalog)
        async with self._sessionmaker() as session:
            await mastery.ensure_current(
                session, conversation.user_id, rules=rules, catalog=catalog
            )
            affected = await record_chat_evidence(
                session,
                user_id=conversation.user_id,
                conversation_id=conversation.id,
                message_ids=list(learner_ids.values()),
                items=items,
            )
            await mastery.refresh(
                session, conversation.user_id, affected, rules=rules, catalog=catalog
            )
            await session.commit()
        if items:
            wrong = sum(not item.correct for item in items)
            logger.info(
                "recorded %d mistakes and %d successes in conversation %s",
                wrong,
                len(items) - wrong,
                conversation.id,
            )
        return items

    async def _record_reflection_activity(
        self,
        conversation: Conversation,
        new: Sequence[BaseMessage],
        status: ActivityStatus,
        applied: Applied | None,
        items: Sequence[ChatEvidence],
        duration_ms: int | None,
    ) -> None:
        """What reflection did, for the learner (ADR 0013 §3): memory changes on the
        batch's last learner message, grammar tags on each message they came from."""
        turns = list(reflection.learner_message_ids(new).values())
        if not turns:
            return
        memory = MemoryChanges(
            added=list(applied.added) if applied else [],
            updated=list(applied.updated) if applied else [],
            deleted=applied.deleted if applied else 0,
            profile_fields=list(applied.profile_fields) if applied else [],
        )
        steps: list[tuple[str, str, MemoryChanges | GrammarTags]] = [
            (turns[-1], "reflect_memory", memory)
        ]
        for turn in turns:
            own = [item for item in items if item.message_id == turn]
            tags = GrammarTags(
                mistakes=[
                    GrammarMistake(
                        kc_id=item.kc_id,
                        error_type=item.error_type,
                        severity=item.severity,
                        original=item.original or "",
                        correction=item.correction,
                    )
                    for item in own
                    if not item.correct and item.error_type and item.severity
                ],
                used_correctly=[item.kc_id for item in own if item.correct],
            )
            steps.append((turn, "grammar_tagging", tags))
        await self._record_activity(conversation, steps, status, duration_ms)

    async def _record_activity(
        self,
        conversation: Conversation,
        steps: Sequence[tuple[str, str, activity.Summary]],
        status: ActivityStatus,
        duration_ms: int | None,
    ) -> None:
        """Best effort: the learner's memories and evidence matter more than the log."""
        try:
            async with self._sessionmaker() as session:
                for turn_id, name, summary in steps:
                    await activity.record(
                        session,
                        user_id=conversation.user_id,
                        conversation_id=conversation.id,
                        turn_id=turn_id,
                        name=name,
                        status=status,
                        summary=summary,
                        duration_ms=duration_ms,
                    )
                await session.commit()
        except Exception:
            logger.exception("recording activity failed for conversation %s", conversation.id)

    async def _summarize(
        self,
        conversation: Conversation,
        ctx: TenantProviderContext,
        messages: Sequence[BaseMessage],
        job: _Job,
        config: RunnableConfig,
    ) -> None:
        new, _ = split_after(messages, conversation.summarized_message_id, len(messages))
        turns = sum(isinstance(m, HumanMessage) for m in new)
        if turns == 0 or (turns < SUMMARY_EVERY_TURNS and not job.finish):
            return
        async with self._sessionmaker() as session:
            previous = await session.scalar(
                select(Memory.content).where(
                    Memory.user_id == conversation.user_id,
                    Memory.kind == "episode",
                    Memory.source_conversation_id == conversation.id,
                )
            )
        episode_id: uuid.UUID | None = None
        status: ActivityStatus
        with timed() as watch:
            try:
                summary = await _twice(
                    lambda: reflection.summarize(
                        ctx,
                        previous=previous or "",
                        messages=new,
                        language=job.language,
                        config=config,
                    )
                )
            except NoModelConfiguredError:
                summary, status = None, "skipped"
            else:
                status = "ok" if summary is not None else "failed"
            if summary is not None and summary.strip():
                embedder = memory_embedder(ctx)
                async with self._sessionmaker() as session:
                    episode = await service.upsert_episode(
                        session,
                        tenant_id=conversation.tenant_id,
                        user_id=conversation.user_id,
                        conversation_id=conversation.id,
                        content=summary[: service.MAX_CONTENT_LENGTH],
                        embedder=embedder,
                    )
                    episode_id = episode.id
        # An empty summary (nothing worth keeping) is not worth showing either.
        learner_turns = list(reflection.learner_message_ids(new).values())
        if learner_turns and (status != "ok" or episode_id is not None):
            await self._record_activity(
                conversation,
                [(learner_turns[-1], "summarize", SummaryUpdate(episode_id=episode_id))],
                status,
                watch.ms,
            )
        await self._move_cursor(conversation.id, summarized_message_id=new[-1].id)

    async def _move_cursor(self, conversation_id: uuid.UUID, **cursor: str | None) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                # Keep updated_at: reflection must not reorder the conversation list.
                .values(**cursor, updated_at=Conversation.updated_at)
            )
            await session.commit()


def split_after(
    messages: Sequence[BaseMessage], cursor: str | None, backlog: int
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """(messages after `cursor`, the ones up to it). Without a usable cursor: the last
    `backlog` messages count as new."""
    ids = [m.id for m in messages]
    if cursor is not None and cursor in ids:
        at = ids.index(cursor) + 1
    else:
        at = max(len(messages) - backlog, 0)
    return list(messages[at:]), list(messages[:at])


async def _twice[T](call: Callable[[], Awaitable[T]]) -> T | None:
    """One retry; None when it keeps failing. A missing model is not retried: its
    NoModelConfiguredError is raised, so the step is shown as skipped, not failed."""
    for attempt in (1, 2):
        try:
            return await call()
        except NoModelConfiguredError:
            raise
        except Exception:
            logger.warning("reflection call failed (attempt %d)", attempt, exc_info=True)
    return None
