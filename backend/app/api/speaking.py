"""Speaking practice (ADR 0029, task 58): the scenarios, starting a session, ending it
with a summary, the history, fixing a transcript, deleting a session.

The turns themselves go through `/conversations/{id}/opening` and `.../messages`, like
any conversation's; speaking conversations are left out of the chat list (Q58g).
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.exercise.worker import structured_call
from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import get_rules
from app.agents.chat_graph import ChatGraph
from app.api.errors import api_error
from app.chat import service as chat_service
from app.chat.locks import ConversationLocks
from app.chat.service import thread_config
from app.db.models import Conversation, SpeakingSession
from app.deps import ChatGraphDep, CurrentTenant, CurrentUser, SessionDep
from app.memory.reflection import LOCALE_COOKIE
from app.memory.service import get_profile
from app.providers.errors import NoModelConfiguredError
from app.providers.llm import get_chat_models
from app.providers.tenant import load_provider_context
from app.speaking import sessions
from app.speaking.evidence import mark_corrected
from app.speaking.scenarios import Scenario, get_scenarios
from app.speaking.summary import TASK as SUMMARY_TASK

router = APIRouter(prefix="/speaking", tags=["speaking"])

PAGE_SIZE = 20


class ScenarioOut(BaseModel):
    id: str
    title_en: str
    title_zh: str
    levels: tuple[CefrLevel, CefrLevel]
    learner_goal_en: str
    learner_goal_zh: str
    target_expressions: tuple[str, ...]
    # Within its level range for this learner; the rest are shown folded (ADR 0029 §1).
    suits: bool

    @classmethod
    def of(cls, scenario: Scenario, suits: bool) -> "ScenarioOut":
        return cls(
            id=scenario.id,
            title_en=scenario.title_en,
            title_zh=scenario.title_zh,
            levels=scenario.levels,
            learner_goal_en=scenario.learner_goal_en,
            learner_goal_zh=scenario.learner_goal_zh,
            target_expressions=scenario.target_expressions,
            suits=suits,
        )


class ScenariosOut(BaseModel):
    level: CefrLevel
    scenarios: list[ScenarioOut]


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    scenario_id: str | None
    mode: str
    status: str
    level: str
    turns: int
    spoken_turns: int
    spoken_seconds: float
    intelligibility: str | None
    started_at: datetime
    ended_at: datetime | None


class SessionDetailOut(SessionOut):
    # went_well, mistakes, more_natural, next_expressions, intelligibility; null until
    # summed up, or when nothing was said.
    summary: dict[str, Any] | None
    corrected_message_ids: list[str]


class SessionPage(BaseModel):
    items: list[SessionOut]
    # Pass as `before` for the next page; null on the last.
    next_before: datetime | None


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # null: free talk.
    scenario_id: Annotated[str | None, Field(max_length=40)] = None
    # The UI's locale, for the conversation's title.
    locale: Annotated[str | None, Field(max_length=10)] = None


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: Annotated[str, Field(min_length=1, max_length=64)]


@router.get("/scenarios")
async def list_scenarios(user: CurrentUser, session: SessionDep) -> ScenariosOut:
    profile = await get_profile(session, user.id)
    level = cast(
        CefrLevel, (profile.cefr_level if profile else None) or get_rules().practice.default_level
    )
    return ScenariosOut(
        level=level,
        scenarios=[ScenarioOut.of(i.scenario, i.suits) for i in get_scenarios().for_level(level)],
    )


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    responses={404: {"description": "scenario_not_found"}},
)
async def start_session(
    body: StartIn,
    request: Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
) -> SessionDetailOut:
    """A new speaking conversation; the client then asks for its opening (Q58e)."""
    try:
        row = await sessions.start(
            session,
            tenant.id,
            user.id,
            body.scenario_id,
            locale=body.locale or request.cookies.get(LOCALE_COOKIE),
        )
    except sessions.UnknownScenarioError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "scenario_not_found", "scenario not found"
        ) from exc
    return SessionDetailOut.model_validate(row, from_attributes=True)


@router.get("/sessions")
async def list_sessions(
    request: Request,
    background: BackgroundTasks,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    graph: ChatGraphDep,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = PAGE_SIZE,
) -> SessionPage:
    """The learner's sessions, newest first. Sessions left idle are summed up after
    the response (Q58c); they show as `active` until then."""
    for session_id in await sessions.idle_sessions(
        session, user.id, datetime.now(UTC), get_rules()
    ):
        background.add_task(_end_quietly, request, graph, tenant.id, session_id)
    query = select(SpeakingSession).where(SpeakingSession.user_id == user.id)
    if before is not None:
        query = query.where(SpeakingSession.started_at < before)
    rows = list(
        await session.scalars(
            query.order_by(SpeakingSession.started_at.desc(), SpeakingSession.id).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return SessionPage(
        items=[SessionOut.model_validate(r) for r in rows],
        next_before=rows[-1].started_at if more else None,
    )


@router.get("/sessions/{session_id}", responses={404: {"description": "session_not_found"}})
async def get_session(
    session_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    graph: ChatGraphDep,
) -> SessionDetailOut:
    row = await _owned(session, user.id, session_id)
    if row.id in await sessions.idle_sessions(session, user.id, datetime.now(UTC), get_rules()):
        background.add_task(_end_quietly, request, graph, tenant.id, row.id)
    return SessionDetailOut.model_validate(row)


@router.post(
    "/sessions/{session_id}/end",
    responses={
        404: {"description": "session_not_found"},
        409: {"description": "conversation_busy, no_llm_configured or models_disabled"},
    },
)
async def end_session(
    session_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    graph: ChatGraphDep,
) -> SessionDetailOut:
    """End the session and sum it up (ADR 0029 §5). Answers with the session: `done`
    with its summary, or `failed` when the summary call failed (ending again retries)."""
    row = await _owned(session, user.id, session_id)
    if row.status == "done":
        return SessionDetailOut.model_validate(row)
    try:
        ended = await _end(request, graph, tenant.id, row.id, row.conversation_id)
    except NoModelConfiguredError as exc:
        message = (
            "Every chat model is switched off. Turn one back on in Settings."
            if exc.code == "models_disabled"
            else "No chat model is configured. Add one in Settings."
        )
        raise api_error(status.HTTP_409_CONFLICT, exc.code, message) from exc
    if ended is None:
        raise api_error(
            status.HTTP_409_CONFLICT, "conversation_busy", "A reply is still being generated."
        )
    return SessionDetailOut.model_validate(ended)


@router.post(
    "/sessions/{session_id}/corrections",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "session_not_found or message_not_found"}},
)
async def correct_transcript(
    session_id: uuid.UUID,
    body: CorrectionIn,
    user: CurrentUser,
    session: SessionDep,
    graph: ChatGraphDep,
) -> None:
    """The learner fixed a turn's transcript and sends the fixed text as a new message
    (Q58b): this turn then counts as no evidence. The new message is sent as usual."""
    row = await _owned(session, user.id, session_id)
    state = await graph.aget_state(thread_config(row.conversation_id))
    learner_ids = {
        m.id for m in state.values.get("messages", []) if isinstance(m, HumanMessage) and m.id
    }
    if body.message_id not in learner_ids:
        raise api_error(status.HTTP_404_NOT_FOUND, "message_not_found", "message not found")
    await mark_corrected(session, user.id, row.conversation_id, body.message_id)
    await session.commit()


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "session_not_found"}},
)
async def delete_session(
    session_id: uuid.UUID, user: CurrentUser, session: SessionDep, graph: ChatGraphDep
) -> None:
    """The session, its conversation and summary. Evidence it gave stays, like a
    deleted chat's (ADR 0012)."""
    row = await _owned(session, user.id, session_id)
    conversation = await session.get(Conversation, row.conversation_id)
    checkpointer = graph.checkpointer
    if not isinstance(checkpointer, BaseCheckpointSaver):  # compiled without persistence
        raise RuntimeError("chat graph has no checkpointer")
    if conversation is not None:
        await chat_service.delete_conversation(session, checkpointer, conversation)


async def _owned(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> SpeakingSession:
    row = await session.get(SpeakingSession, session_id)
    if row is None or row.user_id != user_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "session_not_found", "session not found")
    return row


async def _end(
    request: Request,
    graph: ChatGraph,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> SpeakingSession | None:
    """Sum up under the conversation's lock; None when a reply is being generated.
    Raises NoModelConfiguredError before taking the lock."""
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        ctx = await load_provider_context(session, tenant_id)
        user_id = await session.scalar(
            select(SpeakingSession.user_id).where(SpeakingSession.id == session_id)
        )
    get_chat_models(ctx, SUMMARY_TASK)  # raises before anything is ended
    config: RunnableConfig = {
        "metadata": {"user_id": str(user_id), "conversation_id": str(conversation_id)},
    }
    call = structured_call(ctx, config, SUMMARY_TASK)
    locks: ConversationLocks = request.app.state.conversation_locks
    if not locks.acquire(conversation_id):
        return None
    try:
        return await sessions.end(maker, graph, session_id, call)
    finally:
        locks.release(conversation_id)


async def _end_quietly(
    request: Request, graph: ChatGraph, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        conversation_id = await session.scalar(
            select(SpeakingSession.conversation_id).where(SpeakingSession.id == session_id)
        )
    if conversation_id is None:
        return
    try:
        await _end(request, graph, tenant_id, session_id, conversation_id)
    except NoModelConfiguredError:  # stays active until a model is set up
        pass
