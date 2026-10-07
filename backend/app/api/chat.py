"""Conversations (P0 plan §6.2). Someone else's conversation is always a 404."""

import dataclasses
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.activity.service import DatabaseActivity
from app.adaptive.kc.catalog import CefrLevel, get_grammar_catalog
from app.agents.routing import Route, route_for
from app.api.attachments import AttachmentOut
from app.api.errors import api_error
from app.api.vocab import TimeZone
from app.attachments import service as attachment_service
from app.attachments.context import DatabaseAttachments
from app.attachments.service import AttachmentNotFoundError, AttachmentStateError
from app.cards.runtime import DatabaseTutorTools
from app.chat import service, translate
from app.chat.locks import ConversationLocks
from app.chat.planning import DatabasePlanning, PlanningPurpose
from app.chat.practice import DatabasePractice
from app.chat.service import ConversationNotFoundError
from app.chat.turn import (
    OPENING_TURN_ID,
    CardEvent,
    DoneEvent,
    begin_turn,
    new_message_id,
    stream_reply,
)
from app.chat.writing import DatabaseWriting
from app.db.models import Attachment, Conversation
from app.deps import ChatGraphDep, CurrentTenant, CurrentUser, SessionDep
from app.memory.context import DatabaseLearner
from app.memory.embedding import memory_embedder
from app.memory.reflection import LOCALE_COOKIE, memory_language
from app.memory.worker import ReflectionWorker
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from app.providers.llm import get_chat_models
from app.providers.tenant import load_provider_context
from app.services.vocab.scheduler import learner_zone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["chat"])


class FocusKcOut(BaseModel):
    id: str
    name_en: str
    name_zh: str
    cefr: CefrLevel


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    # The grammar point a practice conversation is about; None for free chat.
    focus_kc: FocusKcOut | None = None
    # "planning": a study-planning conversation (ADR 0015 §6); "daily": the dashboard's
    # conversation of the day (ADR 0016); None otherwise.
    purpose: PlanningPurpose | None = None

    @classmethod
    def of(cls, conversation: Conversation) -> "ConversationOut":
        kc = get_grammar_catalog().get(conversation.focus_kc_id or "")
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            focus_kc=FocusKcOut.model_validate(kc, from_attributes=True) if kc else None,
            purpose=_purpose(conversation),
        )


class ConversationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A grammar KC id: starts a practice conversation on it (P1 plan §7.5.3).
    focus_kc_id: Annotated[str | None, Field(max_length=64)] = None
    # "planning": a study-planning conversation (ADR 0015 §6); "daily": today's
    # dashboard conversation, returned if it exists (ADR 0016). Not with focus_kc_id.
    purpose: PlanningPurpose | None = None
    # The UI's locale, for the practice title; the cookie is only set once the
    # learner picks a language by hand.
    locale: Annotated[str | None, Field(max_length=10)] = None
    # The browser's IANA time zone, for "today" when the profile has none.
    tz: Annotated[str | None, Field(max_length=64)] = None


class MessageOut(BaseModel):
    id: str | None
    role: Literal["user", "assistant"]
    content: str
    attachments: list[AttachmentOut] = []


def _purpose(conversation: Conversation) -> PlanningPurpose | None:
    match conversation.purpose:
        case "planning" | "daily" as purpose:
            return purpose
        case _:
            return None


async def _owned(
    session: SessionDep, user: CurrentUser, conversation_id: uuid.UUID
) -> Conversation:
    try:
        return await service.get_owned_conversation(session, user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "conversation_not_found", "conversation not found"
        ) from exc


@router.get("")
async def list_conversations(user: CurrentUser, session: SessionDep) -> list[ConversationOut]:
    rows = await service.list_conversations(session, user.id)
    return [ConversationOut.of(c) for c in rows]


@router.get("/today")
async def get_todays_conversation(
    user: CurrentUser, session: SessionDep, tz: TimeZone = None
) -> ConversationOut | None:
    """Today's daily conversation (ADR 0016 §1), or null before the learner's first
    message of the day."""
    zone = await learner_zone(session, user.id, tz)
    conversation = await service.daily_conversation(session, user.id, zone)
    return ConversationOut.of(conversation) if conversation else None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {
            "description": "an unstarted practice conversation on the same KC, an "
            "empty planning conversation, or today's daily conversation, reused"
        },
        422: {"description": "validation_error, unknown_kc or conflicting_purpose"},
    },
)
async def create_conversation(
    request: Request,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    graph: ChatGraphDep,
    body: ConversationIn | None = None,
) -> ConversationOut:
    body = body or ConversationIn()
    focus = None
    conversation = None
    if body.focus_kc_id is not None and body.purpose is not None:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "conflicting_purpose",
            "a conversation is for practice or for planning, not both",
        )
    if body.purpose == "planning":
        conversation = await service.unstarted_planning(session, graph, user.id)
    locale = body.locale or request.cookies.get(LOCALE_COOKIE)
    if body.purpose == "daily":
        zone = await learner_zone(session, user.id, body.tz)
        conversation, created = await service.todays_daily(
            session, tenant.id, user.id, zone, locale=locale
        )
        if created:
            response.status_code = status.HTTP_201_CREATED
            await _reflection(request).finish_previous(
                user.id,
                except_conversation_id=conversation.id,
                language=memory_language(request.cookies.get(LOCALE_COOKIE)),
            )
        else:
            response.status_code = status.HTTP_200_OK
        return ConversationOut.of(conversation)
    if body.focus_kc_id is not None:
        focus = get_grammar_catalog().get(body.focus_kc_id)
        if focus is None:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_kc", "unknown grammar point"
            )
        conversation = await service.unstarted_practice(session, graph, user.id, focus.id)
    if conversation is not None:
        response.status_code = status.HTTP_200_OK
    else:
        conversation = await service.create_conversation(
            session,
            tenant.id,
            user.id,
            focus=focus,
            purpose=body.purpose,
            locale=locale,
        )
    # Starting afresh is when the conversation the learner left gets its summary.
    await _reflection(request).finish_previous(
        user.id,
        except_conversation_id=conversation.id,
        language=memory_language(request.cookies.get(LOCALE_COOKIE)),
    )
    return ConversationOut.of(conversation)


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, graph: ChatGraphDep
) -> list[MessageOut]:
    conversation = await _owned(session, user, conversation_id)
    history = await service.get_history(graph, conversation)
    attached = await service.attachments_by_message(session, conversation, history)
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            attachments=[AttachmentOut.of(a) for a in attached.get(m.id or "", [])],
        )
        for m in history
    ]


class TranslateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: translate.Target


class TranslationOut(BaseModel):
    message_id: str
    target: translate.Target
    text: str


@router.post("/{conversation_id}/messages/{message_id}/translate")
async def translate_message(
    conversation_id: uuid.UUID,
    message_id: Annotated[str, Path(max_length=100)],
    body: TranslateIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    graph: ChatGraphDep,
) -> TranslationOut:
    """A tutor message in the other language (ADR 0017 §4): made by a model the first
    time, then kept."""
    conversation = await _owned(session, user, conversation_id)
    ctx = await load_provider_context(session, tenant.id)
    config: RunnableConfig = {
        "metadata": {"user_id": str(user.id), "conversation_id": str(conversation.id)}
    }
    try:
        text = await translate.translate(
            session, graph, ctx, conversation, message_id, body.target, config
        )
    except translate.MessageNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "message_not_found", "no such tutor message"
        ) from exc
    except NoModelConfiguredError as exc:
        raise _conflict(exc.code, _no_model_message(exc, "chat")) from exc
    except Exception as exc:
        # Details stay in the server log; vendor errors can echo input.
        logger.exception("translating a message in conversation %s failed", conversation_id)
        raise api_error(
            status.HTTP_502_BAD_GATEWAY, "llm_unavailable", "The model is unavailable right now."
        ) from exc
    return TranslationOut(message_id=message_id, target=body.target, text=text)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, graph: ChatGraphDep
) -> None:
    conversation = await _owned(session, user, conversation_id)
    checkpointer = graph.checkpointer
    if not isinstance(checkpointer, BaseCheckpointSaver):  # compiled without persistence
        raise RuntimeError("chat graph has no checkpointer")
    await service.delete_conversation(session, checkpointer, conversation)


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(max_length=4000)] = ""
    # Uploaded and ready attachments of this conversation (ADR 0008 §3).
    attachment_ids: Annotated[
        list[uuid.UUID], Field(max_length=attachment_service.MAX_PER_MESSAGE)
    ] = []

    @model_validator(mode="after")
    def _not_empty(self) -> "MessageIn":
        if not self.content.strip() and not self.attachment_ids:
            raise ValueError("a message needs text or an attachment")
        return self


@dataclass(frozen=True)
class Turn:
    conversation_id: uuid.UUID
    providers: TenantProviderContext
    text: str | None  # None: an opening
    message_id: str
    focus_kc_id: str | None
    # A planning or daily conversation: the turn gets the learning engine's brief.
    planning: PlanningPurpose | None

    @property
    def route(self) -> Route:
        return route_for(self.focus_kc_id)

    @property
    def free_chat(self) -> bool:
        """A learner's message in free chat: the supervisor may hand it to another
        coach (task 38.4)."""
        return self.route is Route.TUTOR and self.planning is None and self.text is not None


def _conflict(code: str, message: str) -> HTTPException:
    return api_error(status.HTTP_409_CONFLICT, code, message)


async def start_turn(
    conversation_id: uuid.UUID,
    body: MessageIn,
    request: Request,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
) -> AsyncIterator[Turn]:
    """Everything that can fail with a proper HTTP status, before the stream starts.

    FastAPI sends the SSE response headers (200) before running the endpoint body, so
    404/409 must be raised here. Being a yield dependency on the request scope, the
    lock is released only after the stream ends - including client disconnects.
    """
    # Appended to FastAPI's own "no-cache". Without no-transform, Next's rewrite proxy
    # gzips the stream and buffers the whole reply (ADR 0003). Set here because the
    # endpoint body runs only after the headers are sent.
    response.headers["Cache-Control"] = "no-transform"
    conversation = await _owned(session, user, conversation_id)
    attachments = await _message_attachments(session, conversation, body.attachment_ids)
    # A turn with images is answered by the vision route (ADR 0008 §4).
    task = "vision" if any(a.kind == "image" for a in attachments) else "chat"
    providers = await _providers_for(session, tenant.id, task)
    # A voice message may come without typed text: its transcript is the text.
    text = body.content.strip() or next(
        (a.text or "" for a in attachments if a.kind == "audio"), ""
    )
    locks: ConversationLocks = request.app.state.conversation_locks
    if not locks.acquire(conversation.id):
        raise _conflict("conversation_busy", "A reply is still being generated.")
    try:
        message_id = new_message_id()
        try:
            await begin_turn(
                session, conversation, text, message_id=message_id, attachments=attachments
            )
        except AttachmentStateError as exc:
            raise _conflict(exc.code, exc.message) from exc
        yield Turn(
            conversation.id,
            providers,
            text,
            message_id,
            conversation.focus_kc_id,
            _purpose(conversation),
        )
    finally:
        locks.release(conversation.id)


async def start_opening(
    conversation_id: uuid.UUID,
    request: Request,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    graph: ChatGraphDep,
) -> AsyncIterator[Turn]:
    """Like start_turn, for the tutor's first message in a practice or planning
    conversation."""
    response.headers["Cache-Control"] = "no-transform"
    conversation = await _owned(session, user, conversation_id)
    # A daily conversation has no opening: the tutor answers the learner's first message.
    planning = conversation.purpose == "planning"
    if conversation.focus_kc_id is None and not planning:
        raise _conflict("not_practice", "Only a practice or planning conversation opens by itself.")
    providers = await _providers_for(session, tenant.id, "chat")
    locks: ConversationLocks = request.app.state.conversation_locks
    if not locks.acquire(conversation.id):
        raise _conflict("conversation_busy", "A reply is still being generated.")
    try:
        # Checked under the lock: two tabs opening at once must not both get a reply.
        if await service.get_history(graph, conversation):
            raise _conflict("conversation_started", "This conversation has already started.")
        await begin_turn(session, conversation, "")  # moves it to the top of the list
        yield Turn(
            conversation.id,
            providers,
            None,
            OPENING_TURN_ID,
            conversation.focus_kc_id,
            "planning" if planning else None,
        )
    finally:
        locks.release(conversation.id)


async def _providers_for(
    session: SessionDep, tenant_id: uuid.UUID, task: str
) -> TenantProviderContext:
    providers = await load_provider_context(session, tenant_id)
    try:
        get_chat_models(providers, task)  # resolves the route (and warms the cache)
    except NoModelConfiguredError as exc:
        what = "image-capable" if task == "vision" else "chat"
        raise _conflict(exc.code, _no_model_message(exc, what)) from exc
    return providers


def _no_model_message(exc: NoModelConfiguredError, what: str) -> str:
    if exc.code == "models_disabled":
        return f"Every {what} model is switched off. Turn one back on in Settings."
    return f"No {what} model is configured. Add one in Settings."


async def _message_attachments(
    session: SessionDep, conversation: Conversation, attachment_ids: list[uuid.UUID]
) -> list[Attachment]:
    try:
        return await attachment_service.attachments_for_message(
            session, conversation, attachment_ids
        )
    except AttachmentNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "attachment_not_found", "attachment not found"
        ) from exc
    except AttachmentStateError as exc:
        if exc.code in ("invalid_attachments", "too_many_images"):
            raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, exc.message) from exc
        raise _conflict(exc.code, exc.message) from exc


@router.post(
    "/{conversation_id}/messages",
    response_class=EventSourceResponse,
    responses={
        404: {"description": "conversation_not_found or attachment_not_found"},
        409: {
            "description": "no_llm_configured, no_vision_model, models_disabled, "
            "conversation_busy, "
            "attachment_not_ready or attachment_sent"
        },
        422: {"description": "validation_error, invalid_attachments or too_many_images"},
    },
)
async def send_message(
    turn: Annotated[Turn, Depends(start_turn)],
    request: Request,
    user: CurrentUser,
    graph: ChatGraphDep,
) -> AsyncIterator[ServerSentEvent]:
    """Stream the tutor's reply: `token`* then `done`, or `error` (ADR 0003); `activity`
    events for the steps of the turn may come before and between tokens (ADR 0013)."""
    async for event in _reply(turn, request, user, graph):
        yield event


@router.post(
    "/{conversation_id}/opening",
    response_class=EventSourceResponse,
    responses={
        404: {"description": "conversation_not_found"},
        409: {
            "description": "not_practice, no_llm_configured, models_disabled, "
            "conversation_busy or "
            "conversation_started"
        },
    },
)
async def open_practice(
    turn: Annotated[Turn, Depends(start_opening)],
    request: Request,
    user: CurrentUser,
    graph: ChatGraphDep,
) -> AsyncIterator[ServerSentEvent]:
    """The tutor's first message in a new practice (Q19a) or planning (ADR 0015 §6)
    conversation, streamed like a reply; `done.turn_id` is "opening". Nothing is added
    on the learner's behalf."""
    async for event in _reply(turn, request, user, graph):
        yield event


async def _reply(
    turn: Turn, request: Request, user: CurrentUser, graph: ChatGraphDep
) -> AsyncIterator[ServerSentEvent]:
    sessionmaker = request.app.state.sessionmaker
    route = turn.route
    practice: DatabasePractice | None = None
    tools: DatabaseTutorTools | None = None
    planning: DatabasePlanning | None = None
    writing: DatabaseWriting | None = None
    match route:
        case Route.GRAMMAR_COACH:
            # Practice stays on its grammar point: no tools (ADR 0015 §2).
            assert turn.focus_kc_id is not None  # route_for
            practice = DatabasePractice(sessionmaker, user.id, turn.focus_kc_id)
        case Route.TUTOR:
            # Read once per turn, for the prompt and for the cards the tools may show.
            if turn.planning:
                planning = DatabasePlanning(sessionmaker, user.id, turn.planning)
            tools = DatabaseTutorTools(
                sessionmaker,
                user.id,
                turn.conversation_id,
                turn.message_id,
                scope=planning.scope if planning else None,
            )
            if turn.free_chat:  # the supervisor may hand it to writing_coach
                writing = DatabaseWriting(
                    sessionmaker,
                    request.app.state.writing_worker,
                    user_id=user.id,
                    tenant_id=turn.providers.tenant_id,
                    conversation_id=turn.conversation_id,
                    turn_id=turn.message_id,
                )
    async for event in stream_reply(
        graph,
        conversation_id=turn.conversation_id,
        user_id=user.id,
        providers=turn.providers,
        text=turn.text,
        message_id=turn.message_id,
        attachments=DatabaseAttachments(sessionmaker, turn.conversation_id),
        learner=DatabaseLearner(
            sessionmaker, user.id, turn.conversation_id, memory_embedder(turn.providers)
        ),
        activity=DatabaseActivity(sessionmaker, user.id, turn.conversation_id, turn.message_id),
        route=route,
        classify=turn.free_chat,
        writing=writing,
        practice=practice,
        tools=tools,
        planning=planning,
    ):
        if isinstance(event, CardEvent):  # the card itself, like GET .../cards items
            yield ServerSentEvent(event=event.event, data=event.card)
            continue
        data = dataclasses.asdict(event)
        yield ServerSentEvent(event=data.pop("event"), data=data)
        # After the reply is out, never before: memory work must not delay it. An
        # opening has nothing from the learner to reflect on.
        if isinstance(event, DoneEvent) and turn.text is not None:
            _reflection(request).schedule(
                turn.conversation_id,
                language=memory_language(request.cookies.get(LOCALE_COOKIE)),
            )


def _reflection(request: Request) -> ReflectionWorker:
    worker: ReflectionWorker = request.app.state.reflection_worker
    return worker
