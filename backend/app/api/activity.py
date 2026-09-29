"""What the tutor did on each turn of a conversation (ADR 0013 §3)."""

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.activity import service
from app.adaptive.kc.catalog import get_grammar_catalog
from app.api.errors import api_error
from app.chat.service import ConversationNotFoundError, get_owned_conversation
from app.db.models import Memory
from app.deps import CurrentUser, SessionDep
from app.memory.worker import ReflectionWorker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["activity"])


class ActivityOut(BaseModel):
    """Same fields as the chat stream's `activity` event."""

    turn_id: str
    name: str
    kind: str
    call_id: str
    status: str
    duration_ms: int | None
    summary: dict[str, Any]
    created_at: datetime


class MemoryRef(BaseModel):
    kind: str
    content: str


class KCRef(BaseModel):
    name_en: str
    name_zh: str
    cefr: str


class ConversationActivity(BaseModel):
    activities: list[ActivityOut]
    # Referenced memories that still exist, as they read now; missing ones were deleted.
    memories: dict[uuid.UUID, MemoryRef]
    kcs: dict[str, KCRef]
    # Background work on this conversation is still queued or running.
    pending: bool


@router.get("/{conversation_id}/activity")
async def get_activity(
    conversation_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    turn: Annotated[list[Annotated[str, Field(max_length=64)]] | None, Query(max_length=50)] = None,
) -> ConversationActivity:
    """`?turn=<learner message id>` (repeatable) narrows it to those turns."""
    try:
        conversation = await get_owned_conversation(session, user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "conversation_not_found", "conversation not found"
        ) from exc
    rows = await service.list_activities(session, user.id, conversation.id, turn_ids=turn)
    memory_ids: set[uuid.UUID] = set()
    kc_ids: set[str] = set()
    for row in rows:
        try:
            summary = service.parse_summary(row)
        except ValidationError:
            logger.warning("unreadable %s activity %d", row.name, row.id)
            continue
        memory_ids.update(service.memory_refs(summary))
        kc_ids.update(service.kc_refs(summary))
    memories: list[Memory] = []
    if memory_ids:
        found = await session.scalars(
            select(Memory).where(Memory.user_id == user.id, Memory.id.in_(memory_ids))
        )
        memories = list(found)
    catalog = get_grammar_catalog()
    kcs = {kc_id: kc for kc_id in kc_ids if (kc := catalog.get(kc_id)) is not None}
    worker: ReflectionWorker = request.app.state.reflection_worker
    return ConversationActivity(
        activities=[
            ActivityOut(
                turn_id=r.turn_id,
                name=r.name,
                kind=r.kind,
                call_id=r.call_id,
                status=r.status,
                duration_ms=r.duration_ms,
                summary=r.summary,
                created_at=r.created_at,
            )
            for r in rows
        ],
        memories={m.id: MemoryRef(kind=m.kind, content=m.content) for m in memories},
        kcs={
            kc_id: KCRef(name_en=kc.name_en, name_zh=kc.name_zh, cefr=kc.cefr)
            for kc_id, kc in kcs.items()
        },
        pending=worker.enabled and worker.is_busy(conversation.id),
    )
