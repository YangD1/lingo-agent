"""Learner profile and long-term memories (ADR 0009).

Every query is scoped to one user: a memory id from someone else behaves exactly like
a missing one. Embeddings are computed before touching the database, so no transaction
(and pooled connection) is held while a vendor call is in flight.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.db.models import Memory, UserProfile
from app.memory.embedding import MemoryEmbedder

type MemoryKind = Literal["fact", "episode"]

MAX_CONTENT_LENGTH = 1000
# All facts go into the tutor's prompt, so they are capped (the newest win).
MAX_FACTS_IN_CONTEXT = 40
# Fields the learner and reflection may set; `manual_fields` itself is bookkeeping.
PROFILE_FIELDS: frozenset[str] = frozenset(
    {
        "native_language",
        "occupation",
        "goal",
        "target_exam",
        "interests",
        "daily_minutes",
        "explanation_language",
        "cefr_level",
        "timezone",
    }
)


class MemoryNotFoundError(Exception):
    """Missing *or* owned by someone else: callers must not tell the two apart."""


# --- profile ------------------------------------------------------------------------------


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    return await session.get(UserProfile, user_id)


async def update_profile(
    session: AsyncSession,
    user_id: uuid.UUID,
    changes: Mapping[str, Any],
    *,
    by_learner: bool,
) -> UserProfile:
    """Apply `changes`, creating the profile on first use.

    The learner's edits mark the fields as manual; reflection (`by_learner=False`)
    skips manual fields, so it never undoes what the learner wrote themselves.
    """
    unknown = set(changes) - PROFILE_FIELDS
    if unknown:
        raise ValueError(f"not profile fields: {sorted(unknown)}")
    profile = await session.get(UserProfile, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id, interests=[], manual_fields=[])
        session.add(profile)
    manual = set(profile.manual_fields or [])
    for field, value in changes.items():
        if not by_learner and field in manual:
            continue
        setattr(profile, field, value)
        if by_learner:
            manual.add(field)
    profile.manual_fields = sorted(manual)
    await session.commit()
    await session.refresh(profile)
    return profile


# --- memories -----------------------------------------------------------------------------


def clean_content(content: str) -> str:
    content = content.strip()
    if not content:
        raise ValueError("a memory needs some text")
    if len(content) > MAX_CONTENT_LENGTH:
        raise ValueError(f"a memory is at most {MAX_CONTENT_LENGTH} characters")
    return content


async def list_memories(
    session: AsyncSession, user_id: uuid.UUID, kind: MemoryKind | None = None
) -> list[Memory]:
    query = select(Memory).where(Memory.user_id == user_id)
    if kind is not None:
        query = query.where(Memory.kind == kind)
    rows = await session.scalars(query.order_by(Memory.updated_at.desc(), Memory.id))
    return list(rows)


async def get_memory(session: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
    memory = await session.get(Memory, memory_id)
    if memory is None or memory.user_id != user_id:
        raise MemoryNotFoundError
    return memory


async def add_memory(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: MemoryKind,
    content: str,
    source_conversation_id: uuid.UUID | None = None,
    embedder: MemoryEmbedder | None = None,
) -> Memory:
    content = clean_content(content)
    vector = await embedder.embed(content) if embedder else None
    memory = Memory(
        tenant_id=tenant_id,
        user_id=user_id,
        kind=kind,
        content=content,
        source_conversation_id=source_conversation_id,
    )
    _set_embedding(memory, vector, embedder)
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def update_memory(
    session: AsyncSession,
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
    content: str,
    *,
    embedder: MemoryEmbedder | None = None,
) -> Memory:
    content = clean_content(content)
    vector = await embedder.embed(content) if embedder else None
    memory = await get_memory(session, user_id, memory_id)
    memory.content = content
    _set_embedding(memory, vector, embedder)
    await session.commit()
    await session.refresh(memory)
    return memory


async def upsert_episode(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    embedder: MemoryEmbedder | None = None,
) -> Memory:
    """Replace the conversation's running summary (one per conversation).

    Callers serialize per conversation (the reflection worker does), so a plain
    select-then-write does not race; the partial unique index backs that up.
    """
    content = clean_content(content)
    vector = await embedder.embed(content) if embedder else None
    memory = await session.scalar(
        select(Memory).where(
            Memory.user_id == user_id,
            Memory.kind == "episode",
            Memory.source_conversation_id == conversation_id,
        )
    )
    if memory is None:
        memory = Memory(
            tenant_id=tenant_id,
            user_id=user_id,
            kind="episode",
            source_conversation_id=conversation_id,
            content=content,
        )
        session.add(memory)
    memory.content = content
    _set_embedding(memory, vector, embedder)
    await session.commit()
    await session.refresh(memory)
    return memory


async def delete_memory(session: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
    memory = await get_memory(session, user_id, memory_id)
    await session.delete(memory)
    await session.commit()


async def delete_memories(
    session: AsyncSession, user_id: uuid.UUID, kind: MemoryKind | None = None
) -> int:
    """Really deleted, not hidden: the learner asked to be forgotten."""
    statement = delete(Memory).where(Memory.user_id == user_id)
    if kind is not None:
        statement = statement.where(Memory.kind == kind)
    result: CursorResult[Any] = await session.execute(statement)  # type: ignore[assignment]
    await session.commit()
    return result.rowcount


def _set_embedding(
    memory: Memory, vector: list[float] | None, embedder: MemoryEmbedder | None
) -> None:
    # A stale vector would rank the new text by the old one's meaning: drop it.
    memory.embedding = vector
    memory.embedding_model = embedder.model_id if embedder and vector is not None else None


# --- reading for the tutor ----------------------------------------------------------------


async def facts_for_context(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = MAX_FACTS_IN_CONTEXT
) -> list[Memory]:
    rows = await session.scalars(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.kind == "fact")
        .order_by(Memory.updated_at.desc(), Memory.id)
        .limit(limit)
    )
    return list(rows)


async def relevant_episodes(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    embedder: MemoryEmbedder | None,
    limit: int = 3,
    exclude_conversation_id: uuid.UUID | None = None,
) -> list[Memory]:
    """Summaries of other conversations, most related to `query` first.

    With an embedding model: nearest by cosine distance among vectors from that same
    model, then topped up with the most recent ones (rows embedded by another model, or
    not at all). Without one, or when there are no more than `limit` anyway: the most
    recent.
    """
    base = select(Memory).where(Memory.user_id == user_id, Memory.kind == "episode")
    if exclude_conversation_id is not None:
        base = base.where(Memory.source_conversation_id.is_distinct_from(exclude_conversation_id))
    recent = list(
        await session.scalars(base.order_by(Memory.updated_at.desc(), Memory.id).limit(limit + 1))
    )
    if len(recent) <= limit:
        return recent  # all of them anyway: skip the embedding call and its latency
    picked: list[Memory] = []
    vector = await embedder.embed(query) if embedder and query.strip() else None
    if embedder is not None and vector is not None:
        nearest = await session.scalars(
            base.where(Memory.embedding_model == embedder.model_id)
            .order_by(Memory.embedding.cosine_distance(vector))
            .limit(limit)
        )
        picked = list(nearest)
    if len(picked) < limit:
        rest = base.where(Memory.id.not_in([m.id for m in picked])) if picked else base
        newest = await session.scalars(
            rest.order_by(Memory.updated_at.desc(), Memory.id).limit(limit - len(picked))
        )
        picked.extend(newest)
    return picked


async def memories_missing_embeddings(
    session: AsyncSession, user_id: uuid.UUID, embedder: MemoryEmbedder, *, limit: int = 20
) -> Sequence[Memory]:
    """Rows without a vector from the current model (added before one was configured,
    after the tenant switched models, or when the vendor call failed)."""
    rows = await session.scalars(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.embedding_model.is_distinct_from(embedder.model_id),
        )
        .order_by(Memory.updated_at.desc())
        .limit(limit)
    )
    return list(rows)


async def backfill_embeddings(
    session: AsyncSession, user_id: uuid.UUID, embedder: MemoryEmbedder, *, limit: int = 20
) -> int:
    """Embed up to `limit` rows that lack a current vector; returns how many were done.

    The transaction is closed before the vendor calls and reopened for the writes.
    """
    pending = [
        (m.id, m.content)
        for m in await memories_missing_embeddings(session, user_id, embedder, limit=limit)
    ]
    await session.commit()
    vectors = {memory_id: await embedder.embed(content) for memory_id, content in pending}
    done = 0
    for memory_id, vector in vectors.items():
        if vector is None:
            continue
        memory = await session.get(Memory, memory_id, options=[undefer(Memory.embedding)])
        # Edited meanwhile: the edit computed its own vector (or cleared it).
        if memory is None or memory.content != dict(pending)[memory_id]:
            continue
        memory.embedding = vector
        memory.embedding_model = embedder.model_id
        done += 1
    await session.commit()
    return done
