"""Running placement tests for the API (P1 plan §6.2).

A test is a `placement_sessions` row plus a LangGraph thread of the same id. While it
runs, the question and answers live in the checkpoint; when it ends the graph's
`finish` stores the result (`writeback.save_result`) and the thread is deleted.

Answers to one test are serialized with a transaction-level advisory lock on its id:
the graph's own writes use other connections and never wait on it. An answer to a
question already answered (a retried request) returns the current state unchanged.
"""

import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.placement import flow
from app.adaptive.placement.flow import AnswerInput, PlacementResult, Question
from app.adaptive.placement.items import get_item_bank
from app.adaptive.placement.writeback import save_result
from app.adaptive.rules import get_rules
from app.agents.placement_graph import PlacementContext, PlacementGraph, WordSource, start_state
from app.db.models import PlacementItemStat, PlacementSession


class PlacementNotFoundError(Exception):
    """Missing *or* someone else's: callers must not tell the two apart."""


class WordsMissingError(Exception):
    """The words table has no testable words (ECDICT not imported)."""


class NotInProgressError(Exception):
    """The test was abandoned."""


class StaleQuestionError(Exception):
    """The answer names a question that is neither the current one nor answered."""


@dataclass(frozen=True)
class PlacementRuntime:
    graph: PlacementGraph
    checkpointer: BaseCheckpointSaver[Any]
    sessionmaker: async_sessionmaker[AsyncSession]
    words: WordSource


@dataclass(frozen=True)
class Status:
    placement: PlacementSession
    # What the learner sees (`flow.public`); None when the test is not running.
    question: dict[str, object] | None
    answered: int


def _config(session_id: uuid.UUID) -> RunnableConfig:
    return {"configurable": {"thread_id": str(session_id)}}


def _context(
    runtime: PlacementRuntime, user_id: uuid.UUID, session_id: uuid.UUID
) -> PlacementContext:
    rules, bank = get_rules(), get_item_bank()

    async def save(result: PlacementResult) -> None:
        async with runtime.sessionmaker() as session:
            await save_result(
                session,
                user_id=user_id,
                session_id=session_id,
                result=result,
                rules=rules,
                catalog=get_grammar_catalog(),
                bank=bank,
            )

    return PlacementContext(words=runtime.words, bank=bank, rules=rules, save=save)


async def _lock(session: AsyncSession, key: uuid.UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": str(key)}
    )


async def _own(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> PlacementSession:
    placement = await session.get(PlacementSession, session_id)
    if placement is None or placement.user_id != user_id:
        raise PlacementNotFoundError(session_id)
    return placement


def _answered_ids(values: dict[str, Any]) -> set[str]:
    progress = values["progress"]
    return {f"vocab-{i}" for i in range(len(progress["vocab"]))} | {
        f"grammar-{i}" for i in range(len(progress["grammar"]))
    }


async def _running(
    runtime: PlacementRuntime, placement: PlacementSession
) -> tuple[Question | None, dict[str, Any]]:
    state = await runtime.graph.aget_state(_config(placement.id))
    return state.values.get("question"), state.values


def _count(values: dict[str, Any]) -> int:
    progress = values.get("progress") or {"vocab": [], "grammar": []}
    return len(progress["vocab"]) + len(progress["grammar"])


async def status(
    session: AsyncSession, runtime: PlacementRuntime, user_id: uuid.UUID, session_id: uuid.UUID
) -> Status:
    placement = await _own(session, user_id, session_id)
    return await _status(runtime, placement)


async def _status(runtime: PlacementRuntime, placement: PlacementSession) -> Status:
    if placement.status != "in_progress":
        answered = 0
        if placement.result:
            answers = placement.result["answers"]
            answered = len(answers["vocab"]) + len(answers["grammar"])
        return Status(placement, None, answered)
    question, values = await _running(runtime, placement)
    return Status(placement, flow.public(question) if question else None, _count(values))


async def latest(session: AsyncSession, user_id: uuid.UUID) -> PlacementSession | None:
    """The learner's most recent test, in any state."""
    placement: PlacementSession | None = await session.scalar(
        select(PlacementSession)
        .where(PlacementSession.user_id == user_id)
        .order_by(PlacementSession.created_at.desc(), PlacementSession.id)
        .limit(1)
    )
    return placement


async def start(
    session: AsyncSession, runtime: PlacementRuntime, user_id: uuid.UUID, *, restart: bool = False
) -> Status:
    """Continue the learner's running test, or start one (abandoning it if `restart`)."""
    await _lock(session, user_id)
    running = await session.scalar(
        select(PlacementSession).where(
            PlacementSession.user_id == user_id, PlacementSession.status == "in_progress"
        )
    )
    if running is not None and not restart:
        return await _status(runtime, running)
    if not any((await runtime.words.pool()).bands):
        raise WordsMissingError
    if running is not None:
        # Checkpoints first: a failure leaves the test running rather than orphaned.
        await runtime.checkpointer.adelete_thread(str(running.id))
        running.status = "abandoned"
        await session.flush()
    rules = get_rules()
    difficulties = dict(
        (
            await session.execute(
                select(PlacementItemStat.item_id, PlacementItemStat.difficulty).where(
                    PlacementItemStat.attempts >= rules.placement.grammar.calibrated_min_attempts
                )
            )
        ).all()
    )
    placement = PlacementSession(
        user_id=user_id,
        status="in_progress",
        stage="vocab",
        seed=secrets.randbits(62),
        rules_version=rules.version,
    )
    session.add(placement)
    await session.flush()
    # Still holding the lock: a concurrent start sees the test only once it has its
    # first question, and a failure here rolls the row back with it.
    await runtime.graph.ainvoke(
        start_state(placement.seed, difficulties),
        _config(placement.id),
        context=_context(runtime, user_id, placement.id),
    )
    await session.commit()
    return await _status(runtime, placement)


async def answer(
    session: AsyncSession,
    runtime: PlacementRuntime,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    reply: AnswerInput,
) -> Status:
    """Record an answer; raises InvalidAnswerError, StaleQuestionError, NotInProgressError."""
    placement = await _own(session, user_id, session_id)
    await _lock(session, session_id)
    await session.refresh(placement)
    if placement.status == "done":
        return await _status(runtime, placement)
    if placement.status != "in_progress":
        raise NotInProgressError(session_id)
    question, values = await _running(runtime, placement)
    if question is None:  # pragma: no cover - a running test always waits on a question
        raise NotInProgressError(session_id)
    if reply.get("question_id") != question["id"]:
        if reply.get("question_id") in _answered_ids(values):
            return await _status(runtime, placement)
        raise StaleQuestionError(reply.get("question_id"))
    flow.record(values["progress"], question, reply, get_item_bank())  # validates
    out = await runtime.graph.ainvoke(
        Command(resume=dict(reply)),
        _config(session_id),
        context=_context(runtime, user_id, session_id),
    )
    await session.commit()  # releases the lock; the graph's writes are committed already
    await session.refresh(placement)
    if out.get("result") is not None:
        await runtime.checkpointer.adelete_thread(str(session_id))
        return await _status(runtime, placement)
    following = out.get("question")
    if following is not None and following["stage"] != placement.stage:
        await session.execute(
            update(PlacementSession)
            .where(PlacementSession.id == session_id)
            .values(stage=following["stage"], updated_at=func.now())
        )
        await session.commit()
        await session.refresh(placement)
    return await _status(runtime, placement)
