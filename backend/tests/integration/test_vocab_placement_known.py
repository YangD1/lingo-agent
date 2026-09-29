"""Marking common book words known from the placement result, and undoing it (Q15c)."""

from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.placement.vocab_size import rank_at
from app.adaptive.rules import get_rules
from app.db.models import PlacementSession, User, UserCard, Word
from tests.integration.test_chat_send import login
from tests.integration.test_vocab_api import choose, get

HALF_KNOWN = 4000
# Knows a word with probability 0.9 up to about rank 1920.
UP_TO = rank_at(HALF_KNOWN, 0.9, get_rules().placement.vocab)


async def seed(db: AsyncSession) -> dict[str, int]:
    """cet4 words at ranks 500..10000, and one GRE word inside the range."""
    words = [
        Word(word=f"cet{n}", translation="释义", tags=["cet4"], frq=n * 500) for n in range(1, 21)
    ]
    words.append(Word(word="greword", translation="释义", tags=["gre"], frq=300))
    db.add_all(words)
    await db.commit()
    return {w.word: w.id for w in words}


async def place(db: AsyncSession, *, reliable: bool = True) -> None:
    user = await db.scalar(select(User))
    assert user is not None
    vocab = {"half_known_rank": HALF_KNOWN, "reliable": reliable, "size": 3000}
    db.add(
        PlacementSession(
            user_id=user.id,
            status="done",
            stage="grammar",
            seed=1,
            rules_version="x",
            result={"cefr": "B1", "vocab": vocab, "grammar": {}, "answers": {}},
            finished_at=datetime.now(UTC),
        )
    )
    await db.commit()


async def offer(client: AsyncClient) -> Any:
    return await get(client, "/vocab/placement-known")


async def new_words(client: AsyncClient) -> list[str]:
    queue = await get(client, "/vocab/queue", mode="new")
    return [card["word"]["word"] for card in queue["new"]]


async def test_nothing_to_offer_without_a_test_or_a_book(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed(db_session)
    await login(client)
    assert (await offer(client))["unavailable"] == "no_placement"
    await place(db_session)
    assert (await offer(client))["unavailable"] == "no_book"
    response = await client.post("/vocab/placement-known")
    assert response.json() == {"count": 0}


async def test_an_unreliable_result_offers_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed(db_session)
    await login(client)
    await choose(client, "cet4")
    await place(db_session, reliable=False)
    assert (await offer(client))["unavailable"] == "unreliable"


async def test_mark_known_then_undo(client: AsyncClient, db_session: AsyncSession) -> None:
    ids = await seed(db_session)
    await login(client)
    await choose(client, "cet4", daily_new=50)
    await place(db_session)
    user = await db_session.scalar(select(User))
    assert user is not None
    # A word the learner is already learning is left alone.
    db_session.add(
        UserCard(
            user_id=user.id,
            word_id=ids["cet2"],
            source="book",
            status="learning",
            state=1,
            due=datetime.now(UTC),
        )
    )
    await db_session.commit()

    suggested = await offer(client)
    expected = [f"cet{n}" for n in range(1, 21) if n * 500 <= UP_TO and n != 2]
    assert suggested == {
        "unavailable": None,
        "book_id": "cet4",
        "up_to_rank": UP_TO,
        "count": len(expected),
        "marked": 0,
    }
    assert set(expected) <= set(await new_words(client))

    marked = await client.post("/vocab/placement-known")
    assert marked.json() == {"count": len(expected)}
    after = await offer(client)
    assert (after["count"], after["marked"]) == (0, len(expected))
    assert not set(expected) & set(await new_words(client))
    screen = await get(client, "/vocab/screen")
    assert not set(expected) & {w["word"] for w in screen["words"]}
    # Only the book's words: the GRE word ranked 300 is not marked.
    cards = await db_session.scalars(select(UserCard).where(UserCard.word_id == ids["greword"]))
    assert cards.first() is None

    undone = await client.delete("/vocab/placement-known")
    assert undone.json() == {"count": len(expected)}
    back = await offer(client)
    assert (back["count"], back["marked"]) == (len(expected), 0)
    assert set(expected) <= set(await new_words(client))
    learning = await db_session.scalar(select(UserCard).where(UserCard.word_id == ids["cet2"]))
    assert learning is not None and learning.status == "learning"
