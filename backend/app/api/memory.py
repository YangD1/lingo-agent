"""What the tutor remembers about the learner, which they can read, edit and delete
(ADR 0009). Everything here is the current user's own data only."""

import uuid
from collections.abc import Awaitable
from datetime import datetime
from functools import cache
from typing import Annotated, Any, Literal
from zoneinfo import available_timezones

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.errors import api_error
from app.db.models import Conversation, Memory, UserProfile
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.memory import service
from app.memory.embedding import MemoryEmbedder, memory_embedder
from app.memory.language import DEFAULT_CHAT_LANGUAGE, chat_language
from app.memory.reflection import EXAM_TAGS
from app.providers.tenant import load_provider_context

router = APIRouter(tags=["memory"])

Short = Annotated[str, Field(max_length=200)]


class ProfileOut(BaseModel):
    native_language: str | None = None
    occupation: str | None = None
    goal: str | None = None
    target_exam: str | None = None
    interests: list[str] = []
    daily_minutes: int | None = None
    explanation_language: Literal["zh", "en"] | None = None
    # The language the tutor mainly talks in, as chosen; null: picked by level (ADR 0017).
    chat_language: Literal["zh", "en"] | None = None
    # What applies now: the choice, or the level's default.
    chat_language_effective: Literal["zh", "en"] = DEFAULT_CHAT_LANGUAGE
    # Set by assessment, never by hand (ADR 0010).
    cefr_level: str | None = None
    timezone: str | None = None
    # Fields the learner set themselves: reflection leaves them alone.
    manual_fields: list[str] = []


class ProfilePatch(BaseModel):
    """Only the fields sent are changed; null clears a field."""

    model_config = ConfigDict(extra="forbid")

    native_language: Annotated[str, Field(max_length=50)] | None = None
    occupation: Short | None = None
    goal: Annotated[str, Field(max_length=1000)] | None = None
    target_exam: str | None = None
    interests: Annotated[list[Annotated[str, Field(max_length=100)]], Field(max_length=20)] = []
    daily_minutes: Annotated[int, Field(ge=1, le=600)] | None = None
    explanation_language: Literal["zh", "en"] | None = None
    # null goes back to the level's default.
    chat_language: Literal["zh", "en"] | None = None
    timezone: str | None = None

    @field_validator("native_language", "occupation", "goal")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("target_exam")
    @classmethod
    def _known_exam(cls, value: str | None) -> str | None:
        if value is not None and value not in EXAM_TAGS:
            raise ValueError(f"target_exam must be one of {sorted(EXAM_TAGS)}")
        return value

    @field_validator("interests")
    @classmethod
    def _clean_interests(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(i.strip() for i in value if i.strip()))

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in _timezones():
            raise ValueError("unknown IANA time zone")
        return value


@cache
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())  # reads the tz database from disk


class MemoryOut(BaseModel):
    id: uuid.UUID
    kind: Literal["fact", "episode"]
    content: str
    source_conversation_id: uuid.UUID | None
    # Title of the conversation it came from, if that still exists.
    source_title: str | None
    created_at: datetime
    updated_at: datetime


class MemoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(min_length=1, max_length=service.MAX_CONTENT_LENGTH)]


class Deleted(BaseModel):
    deleted: int


@router.get("/profile")
async def get_profile(user: CurrentUser, session: SessionDep) -> ProfileOut:
    profile = await service.get_profile(session, user.id)
    return _profile_out(profile) if profile else ProfileOut()


@router.patch("/profile")
async def update_profile(body: ProfilePatch, user: CurrentUser, session: SessionDep) -> ProfileOut:
    changes: dict[str, Any] = body.model_dump(exclude_unset=True)
    profile = await service.update_profile(session, user.id, changes, by_learner=True)
    return _profile_out(profile)


@router.get("/memories")
async def list_memories(
    user: CurrentUser, session: SessionDep, kind: Literal["fact", "episode"] | None = None
) -> list[MemoryOut]:
    memories = await service.list_memories(session, user.id, kind)
    return await _memories_out(session, memories)


@router.post("/memories", status_code=status.HTTP_201_CREATED)
async def add_fact(
    body: MemoryIn, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> MemoryOut:
    """The learner tells the tutor something directly."""
    embedder = await _embedder(session, tenant.id)
    memory = await _valid(
        service.add_memory(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            kind="fact",
            content=body.content,
            embedder=embedder,
        )
    )
    return (await _memories_out(session, [memory]))[0]


@router.patch("/memories/{memory_id}")
async def edit_memory(
    memory_id: uuid.UUID,
    body: MemoryIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
) -> MemoryOut:
    embedder = await _embedder(session, tenant.id)
    memory = await _valid(
        service.update_memory(session, user.id, memory_id, body.content, embedder=embedder)
    )
    return (await _memories_out(session, [memory]))[0]


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    try:
        await service.delete_memory(session, user.id, memory_id)
    except service.MemoryNotFoundError as exc:
        raise _not_found() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/memories")
async def delete_memories(
    user: CurrentUser, session: SessionDep, kind: Literal["fact", "episode"] | None = None
) -> Deleted:
    """Forget everything (or every memory of one kind). Really deleted."""
    return Deleted(deleted=await service.delete_memories(session, user.id, kind))


def _profile_out(profile: UserProfile) -> ProfileOut:
    out = ProfileOut.model_validate(profile, from_attributes=True)
    out.chat_language_effective = chat_language(profile.chat_language, profile.cefr_level)
    return out


async def _memories_out(session: SessionDep, memories: list[Memory]) -> list[MemoryOut]:
    ids = {m.source_conversation_id for m in memories if m.source_conversation_id}
    titles = (
        dict(
            (
                await session.execute(
                    select(Conversation.id, Conversation.title).where(Conversation.id.in_(ids))
                )
            ).all()
        )
        if ids
        else {}
    )
    return [
        MemoryOut(
            id=m.id,
            kind=m.kind,
            content=m.content,
            source_conversation_id=m.source_conversation_id,
            source_title=titles.get(m.source_conversation_id) if m.source_conversation_id else None,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in memories
    ]


async def _embedder(session: SessionDep, tenant_id: uuid.UUID) -> MemoryEmbedder | None:
    ctx = await load_provider_context(session, tenant_id)
    # Close the read transaction: the embedding call must not hold a pooled connection.
    await session.commit()
    return memory_embedder(ctx)


async def _valid[T](call: Awaitable[T]) -> T:
    try:
        result = await call
    except service.MemoryNotFoundError as exc:
        raise _not_found() from exc
    except ValueError as exc:
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_memory", str(exc)) from exc
    return result


def _not_found() -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, "memory_not_found", "memory not found")
