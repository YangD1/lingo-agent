import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.auth.service import register_user
from app.db.models import Conversation, Memory, TenantMember, User
from app.memory import embedding as memory_embedding
from app.memory import service
from app.memory.embedding import MemoryEmbedder, memory_embedder
from tests.unit.provider_fixtures import conn, make_config, make_ctx

TOPICS = ("interview", "travel", "grammar")


class TopicEmbeddings(Embeddings):
    """One dimension per topic word: texts about the same topic are close."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    async def aembed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("vendor down")
        lowered = text.lower()
        return [float(lowered.count(t)) + 0.01 for t in TOPICS]


def embedder(model_id: str = "openai:text-embedding-3-small", **kw: Any) -> MemoryEmbedder:
    return MemoryEmbedder(model_id, TopicEmbeddings(**kw))


async def new_user(session: AsyncSession, email: str = "a@example.com") -> tuple[User, uuid.UUID]:
    user = await register_user(session, email, "password123")
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
    )
    assert tenant_id is not None
    return user, tenant_id


async def new_conversation(session: AsyncSession, user: User, tenant_id: uuid.UUID) -> uuid.UUID:
    conversation = Conversation(tenant_id=tenant_id, user_id=user.id)
    session.add(conversation)
    await session.commit()
    return conversation.id


# --- profile ------------------------------------------------------------------------------


async def test_profile_created_on_first_update_and_learner_edits_win(
    db_session: AsyncSession,
) -> None:
    user, _ = await new_user(db_session)
    assert await service.get_profile(db_session, user.id) is None

    profile = await service.update_profile(
        db_session, user.id, {"occupation": "backend developer"}, by_learner=True
    )
    assert profile.occupation == "backend developer"
    assert profile.manual_fields == ["occupation"]
    assert (profile.interests, profile.explanation_language) == ([], None)

    # Reflection may fill other fields but never overwrites the learner's own words.
    profile = await service.update_profile(
        db_session,
        user.id,
        {"occupation": "developer", "interests": ["hiking"]},
        by_learner=False,
    )
    assert (profile.occupation, profile.interests) == ("backend developer", ["hiking"])
    assert profile.manual_fields == ["occupation"]


async def test_profile_rejects_unknown_fields(db_session: AsyncSession) -> None:
    user, _ = await new_user(db_session)
    with pytest.raises(ValueError, match="manual_fields"):
        await service.update_profile(db_session, user.id, {"manual_fields": []}, by_learner=True)


# --- memories -----------------------------------------------------------------------------


async def test_memories_are_private_to_their_owner(db_session: AsyncSession) -> None:
    alice, alice_tenant = await new_user(db_session)
    bob, _ = await new_user(db_session, "b@example.com")
    memory = await service.add_memory(
        db_session, tenant_id=alice_tenant, user_id=alice.id, kind="fact", content=" Likes tea "
    )
    assert memory.content == "Likes tea"

    assert await service.list_memories(db_session, bob.id) == []
    with pytest.raises(service.MemoryNotFoundError):
        await service.update_memory(db_session, bob.id, memory.id, "hacked")
    with pytest.raises(service.MemoryNotFoundError):
        await service.delete_memory(db_session, bob.id, memory.id)
    assert [m.content for m in await service.list_memories(db_session, alice.id)] == ["Likes tea"]


@pytest.mark.parametrize("content", ["   ", "x" * (service.MAX_CONTENT_LENGTH + 1)])
async def test_memory_content_is_validated(db_session: AsyncSession, content: str) -> None:
    user, tenant_id = await new_user(db_session)
    with pytest.raises(ValueError):
        await service.add_memory(
            db_session, tenant_id=tenant_id, user_id=user.id, kind="fact", content=content
        )


async def test_one_episode_per_conversation_kept_after_conversation_is_deleted(
    db_session: AsyncSession,
) -> None:
    user, tenant_id = await new_user(db_session)
    conversation_id = await new_conversation(db_session, user, tenant_id)
    for summary in ("Talked about travel.", "Talked about travel, then an interview."):
        await service.upsert_episode(
            db_session,
            tenant_id=tenant_id,
            user_id=user.id,
            conversation_id=conversation_id,
            content=summary,
        )
    (episode,) = await service.list_memories(db_session, user.id, "episode")
    assert episode.content == "Talked about travel, then an interview."

    await db_session.delete(await db_session.get(Conversation, conversation_id))
    await db_session.commit()
    await db_session.refresh(episode)
    assert episode.source_conversation_id is None


async def test_delete_memories_by_kind(db_session: AsyncSession) -> None:
    user, tenant_id = await new_user(db_session)
    other, other_tenant = await new_user(db_session, "b@example.com")
    for kind in ("fact", "fact", "episode"):
        await service.add_memory(
            db_session,
            tenant_id=tenant_id,
            user_id=user.id,
            kind=kind,
            content=kind,  # type: ignore[arg-type]
        )
    await service.add_memory(
        db_session, tenant_id=other_tenant, user_id=other.id, kind="fact", content="theirs"
    )

    assert await service.delete_memories(db_session, user.id, "fact") == 2
    assert [m.kind for m in await service.list_memories(db_session, user.id)] == ["episode"]
    assert await service.delete_memories(db_session, user.id) == 1
    assert len(await service.list_memories(db_session, other.id)) == 1


async def test_facts_for_context_keeps_the_newest(db_session: AsyncSession) -> None:
    user, tenant_id = await new_user(db_session)
    for i in range(5):
        await service.add_memory(
            db_session, tenant_id=tenant_id, user_id=user.id, kind="fact", content=f"fact {i}"
        )
    facts = await service.facts_for_context(db_session, user.id, limit=3)
    assert [f.content for f in facts] == ["fact 4", "fact 3", "fact 2"]


# --- embeddings and retrieval -------------------------------------------------------------


async def add_episode(
    session: AsyncSession, user: User, tenant_id: uuid.UUID, text: str, emb: MemoryEmbedder | None
) -> Memory:
    return await service.upsert_episode(
        session,
        tenant_id=tenant_id,
        user_id=user.id,
        conversation_id=await new_conversation(session, user, tenant_id),
        content=text,
        embedder=emb,
    )


def contents(memories: Sequence[Memory]) -> list[str]:
    return [m.content for m in memories]


async def test_relevant_episodes_rank_by_meaning_then_recency(db_session: AsyncSession) -> None:
    user, tenant_id = await new_user(db_session)
    emb = embedder()
    interview = await add_episode(db_session, user, tenant_id, "Mock interview practice", emb)
    await add_episode(db_session, user, tenant_id, "Travel plans for Japan", emb)
    await add_episode(db_session, user, tenant_id, "Grammar questions", emb)
    # Embedded by a model the tenant no longer uses: never compared, only a top-up.
    await add_episode(db_session, user, tenant_id, "Interview (old model)", embedder("old:m"))
    await add_episode(db_session, user, tenant_id, "Small talk (no vector)", None)

    found = await service.relevant_episodes(
        db_session, user.id, "help me prepare my interview", embedder=emb, limit=1
    )
    assert contents(found) == ["Mock interview practice"]
    # More than the same-model rows can fill: topped up with the rest, newest first.
    found = await service.relevant_episodes(
        db_session, user.id, "help me prepare my interview", embedder=emb, limit=4
    )
    assert contents(found)[0] == "Mock interview practice"
    assert contents(found)[3] == "Small talk (no vector)"  # the newest of the rest

    found = await service.relevant_episodes(
        db_session,
        user.id,
        "interview",
        embedder=emb,
        limit=4,
        exclude_conversation_id=interview.source_conversation_id,
    )
    assert len(found) == 4 and "Mock interview practice" not in contents(found)


async def test_relevant_episodes_without_embeddings_are_the_most_recent(
    db_session: AsyncSession,
) -> None:
    user, tenant_id = await new_user(db_session)
    for text in ("first", "second", "third"):
        await add_episode(db_session, user, tenant_id, text, None)
    found = await service.relevant_episodes(db_session, user.id, "anything", embedder=None, limit=2)
    assert contents(found) == ["third", "second"]


async def test_few_episodes_are_returned_without_an_embedding_call(
    db_session: AsyncSession,
) -> None:
    user, tenant_id = await new_user(db_session)
    for text in ("first", "second"):
        await add_episode(db_session, user, tenant_id, text, None)
    emb = embedder()
    found = await service.relevant_episodes(db_session, user.id, "anything", embedder=emb, limit=3)
    assert contents(found) == ["second", "first"]
    assert isinstance(emb.embeddings, TopicEmbeddings) and emb.embeddings.calls == []


async def test_failed_embedding_still_saves_and_backfill_fills_it(
    db_session: AsyncSession,
) -> None:
    user, tenant_id = await new_user(db_session)
    memory = await service.add_memory(
        db_session,
        tenant_id=tenant_id,
        user_id=user.id,
        kind="fact",
        content="Preparing for an interview",
        embedder=embedder(fail=True),
    )
    assert memory.embedding_model is None

    emb = embedder()
    assert await service.backfill_embeddings(db_session, user.id, emb) == 1
    assert await service.backfill_embeddings(db_session, user.id, emb) == 0
    stored = await db_session.scalar(
        select(Memory).where(Memory.id == memory.id).options(undefer(Memory.embedding))
    )
    assert stored is not None and stored.embedding_model == emb.model_id
    assert stored.embedding is not None and len(stored.embedding) == len(TOPICS)


async def test_editing_without_embedder_drops_the_stale_vector(db_session: AsyncSession) -> None:
    user, tenant_id = await new_user(db_session)
    memory = await service.add_memory(
        db_session,
        tenant_id=tenant_id,
        user_id=user.id,
        kind="fact",
        content="Likes travel",
        embedder=embedder(),
    )
    assert memory.embedding_model is not None
    edited = await service.update_memory(db_session, user.id, memory.id, "Likes grammar")
    assert edited.embedding_model is None


def test_memory_embedder_follows_the_tenant_embedding_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_embedding, "get_providers_config", make_config)
    assert memory_embedder(make_ctx(conn("deepseek"))) is None
    found = memory_embedder(make_ctx(conn("openai")))
    assert found is not None and found.model_id == "openai:text-embedding-3-small"
