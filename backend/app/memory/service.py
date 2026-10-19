"""Learner profile and long-term memories (ADR 0009).

Every query is scoped to one user: a memory id from someone else behaves exactly like
a missing one. Embeddings are computed before touching the database, so no transaction
(and pooled connection) is held while a vendor call is in flight.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import CursorResult, delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, undefer

from app.db.models import Conversation, Memory, UserProfile
from app.memory import retrieval
from app.memory.embedding import MemoryEmbedder

type MemoryKind = Literal["fact", "episode"]

MAX_CONTENT_LENGTH = 1000
# All facts go into the tutor's prompt, so they are capped (the newest win).
MAX_FACTS_IN_CONTEXT = 40
# Facts reflection replaced or dropped, kept per learner for restoring; older ones are
# deleted (ADR 0053 §4).
MAX_SUPERSEDED = 50
# A learner back after this long starts a new sitting (ADR 0053 §3); a conversation
# left this long gets its summary finished (ADR 0052 §2).
SITTING_GAP = timedelta(minutes=30)
# The newest summaries considered for a turn; older ones are left out.
MAX_EPISODES_SCORED = 500
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
        "chat_language",
        "cefr_level",
        "timezone",
    }
)


class MemoryNotFoundError(Exception):
    """Missing *or* owned by someone else: callers must not tell the two apart."""


# --- profile ------------------------------------------------------------------------------


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    return await session.get(UserProfile, user_id)


async def remember_locale(session: AsyncSession, user_id: uuid.UUID, locale: str) -> None:
    """Keep the UI locale of this request for background work that has none (ADR 0052
    §3); creates the profile on first use, writes only when it changed."""
    table = UserProfile.__table__
    await session.execute(
        insert(UserProfile)
        .values(user_id=user_id, interests=[], manual_fields=[], ui_locale=locale)
        .on_conflict_do_update(
            index_elements=[table.c.user_id],
            set_={"ui_locale": locale},
            where=table.c.ui_locale.is_distinct_from(locale),
        )
    )


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
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: MemoryKind | None = None,
    *,
    include_superseded: bool = False,
) -> list[Memory]:
    query = select(Memory).where(Memory.user_id == user_id)
    if kind is not None:
        query = query.where(Memory.kind == kind)
    if not include_superseded:
        query = query.where(Memory.status == "active")
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


async def supersede_memory(
    session: AsyncSession,
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
    content: str,
    *,
    source_conversation_id: uuid.UUID | None,
    embedder: MemoryEmbedder | None = None,
) -> Memory:
    """Reflection's rewrite of a fact: a new one takes its place and the old one is kept,
    so the learner can see what changed and restore it (ADR 0053 §4)."""
    content = clean_content(content)
    vector = await embedder.embed(content) if embedder else None
    old = await _active_fact(session, user_id, memory_id)
    new = Memory(
        tenant_id=old.tenant_id,
        user_id=user_id,
        kind="fact",
        content=content,
        source_conversation_id=source_conversation_id,
    )
    _set_embedding(new, vector, embedder)
    session.add(new)
    await session.flush()
    old.status = "superseded"
    old.superseded_by_id = new.id
    await _prune_superseded(session, user_id)
    await session.commit()
    await session.refresh(new)
    return new


async def retire_memory(session: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
    """Reflection dropping a fact: kept as superseded, with nothing replacing it."""
    memory = await _active_fact(session, user_id, memory_id)
    memory.status = "superseded"
    await _prune_superseded(session, user_id)
    await session.commit()


async def restore_memory(session: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
    """The learner brings a superseded fact back; whatever replaced it stays."""
    memory = await get_memory(session, user_id, memory_id)
    memory.status = "active"
    memory.superseded_by_id = None
    await session.commit()
    await session.refresh(memory)
    return memory


async def _active_fact(session: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
    memory = await get_memory(session, user_id, memory_id)
    if memory.kind != "fact" or memory.status != "active":
        raise MemoryNotFoundError
    return memory


async def _prune_superseded(session: AsyncSession, user_id: uuid.UUID) -> None:
    keep = (
        select(Memory.id)
        .where(Memory.user_id == user_id, Memory.status == "superseded")
        .order_by(Memory.updated_at.desc(), Memory.id)
        .limit(MAX_SUPERSEDED)
    )
    await session.execute(
        delete(Memory).where(
            Memory.user_id == user_id, Memory.status == "superseded", Memory.id.not_in(keep)
        )
    )


async def delete_memory(session: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
    """Really deleted, with the earlier versions it replaced: the learner asked to forget
    it, not to bring back what it said before."""
    memory = await get_memory(session, user_id, memory_id)
    ids = frontier = {memory.id}
    while frontier:
        found = await session.scalars(
            select(Memory.id).where(
                Memory.user_id == user_id, Memory.superseded_by_id.in_(frontier)
            )
        )
        frontier = set(found) - ids
        ids = ids | frontier
    await session.execute(delete(Memory).where(Memory.id.in_(ids)))
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


def start_sitting(conversation: Conversation, now: datetime) -> None:
    """Begin a new sitting when the learner comes back after SITTING_GAP."""
    if conversation.sitting_started_at is None or now - conversation.updated_at >= SITTING_GAP:
        conversation.sitting_started_at = now


async def sitting_started_at(session: AsyncSession, conversation_id: uuid.UUID) -> datetime | None:
    return await session.scalar(
        select(Conversation.sitting_started_at).where(Conversation.id == conversation_id)
    )


async def facts_for_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = MAX_FACTS_IN_CONTEXT,
    sitting_since: datetime | None = None,
) -> list[Memory]:
    """The newest facts. With `sitting_since`, the ones reflection added after it wait
    for the next sitting, so the prompt prefix stays the same (ADR 0053 §3); the
    learner's own additions (no source conversation) and replacements count at once."""
    query = select(Memory).where(
        Memory.user_id == user_id, Memory.kind == "fact", Memory.status == "active"
    )
    if sitting_since is not None:
        # A replacement is a change to a fact already there, so it counts at once.
        replaced = aliased(Memory)
        replaces = select(replaced.id).where(replaced.superseded_by_id == Memory.id).exists()
        query = query.where(
            or_(
                Memory.created_at <= sitting_since,
                Memory.source_conversation_id.is_(None),
                replaces,
            )
        )
    rows = await session.scalars(query.order_by(Memory.updated_at.desc(), Memory.id).limit(limit))
    return list(rows)


async def relevant_episodes(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    embedder: MemoryEmbedder | None,
    limit: int = 3,
    exclude_conversation_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[Memory]:
    """Summaries of other conversations, most related to `query` first, none
    repeating another (ADR 0052 §4).

    With an embedding model: nearest by cosine distance among vectors from that same
    model. Without one: BM25 over the words (`retrieval.pick`). Either way topped up
    with the most recent. When there are no more than `limit` anyway, no embedding
    call is made.
    """
    base = select(Memory).where(Memory.user_id == user_id, Memory.kind == "episode")
    if exclude_conversation_id is not None:
        base = base.where(Memory.source_conversation_id.is_distinct_from(exclude_conversation_id))
    rows = await session.execute(
        base.add_columns(Conversation.title)
        .outerjoin(Conversation, Conversation.id == Memory.source_conversation_id)
        .order_by(Memory.updated_at.desc(), Memory.id)
        .limit(MAX_EPISODES_SCORED)
    )
    found = [(memory, title or "") for memory, title in rows.all()]
    by_id = {memory.id: memory for memory, _ in found}
    first: list[uuid.UUID] = []
    if len(found) > limit and embedder is not None and query.strip():
        vector = await embedder.embed(query)
        if vector is not None:
            first = list(
                await session.scalars(
                    base.with_only_columns(Memory.id)
                    .where(Memory.embedding_model == embedder.model_id)
                    .order_by(Memory.embedding.cosine_distance(vector))
                    .limit(limit * 3)  # room for the repeats left out
                )
            )
    candidates = [
        retrieval.Candidate(memory.id, memory.content, title, memory.updated_at)
        for memory, title in found
    ]
    picked = retrieval.pick(
        query if len(found) > limit else "",
        candidates,
        limit,
        now=now or datetime.now(UTC),
        first=first,
    )
    return [by_id[key] for key in picked]


async def episodes_by_ids(
    session: AsyncSession, user_id: uuid.UUID, ids: Sequence[uuid.UUID]
) -> list[Memory]:
    """These summaries in this order, without the ones deleted since (ADR 0053 §3)."""
    if not ids:
        return []
    found = await session.scalars(
        select(Memory).where(
            Memory.user_id == user_id, Memory.kind == "episode", Memory.id.in_(ids)
        )
    )
    by_id = {memory.id: memory for memory in found}
    return [by_id[key] for key in ids if key in by_id]


async def memories_missing_embeddings(
    session: AsyncSession, user_id: uuid.UUID, embedder: MemoryEmbedder, *, limit: int = 20
) -> Sequence[Memory]:
    """Rows without a vector from the current model (added before one was configured,
    after the tenant switched models, or when the vendor call failed)."""
    rows = await session.scalars(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.status == "active",
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
