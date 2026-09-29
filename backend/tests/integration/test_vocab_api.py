"""/vocab: word books, the daily queue, reviewing, screening and the own word list."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReviewLog, UserCard, Word
from tests.integration.test_chat_send import login
from tests.integration.test_learner_api import switch_to


async def seed(session: AsyncSession) -> dict[str, int]:
    """Five cet4 words by frequency, an inflected form's lemma, and a GRE word."""
    words = [
        Word(word=name, translation=f"{name} 释义", tags=tags, frq=frq, exchange=exchange)
        for name, tags, frq, exchange in [
            ("common", ["cet4"], 100, None),
            ("middle", ["cet4"], 2000, None),
            ("less", ["cet4"], 5000, None),
            ("rarer", ["cet4"], 8000, None),
            ("rarest", ["cet4"], 9000, None),
            ("go", [], 35, "i:going/p:went/d:gone/3:goes"),
            ("US", [], 900, None),
            ("us", [], 113, None),
            ("100%_pure", [], None, None),
            ("gre1", ["gre"], 50, None),
        ]
    ]
    session.add_all(words)
    await session.commit()
    return {w.word: w.id for w in words}


async def get(client: AsyncClient, url: str, **params: Any) -> Any:
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def choose(client: AsyncClient, book_id: str, daily_new: int | None = None) -> None:
    response = await client.put("/vocab/book", json={"book_id": book_id, "daily_new": daily_new})
    assert response.status_code == 204, response.text


def book(overview: dict[str, Any], book_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(b for b in overview["books"] if b["id"] == book_id)
    return found


def spelled(cards: list[dict[str, Any]]) -> list[str]:
    return [c["word"]["word"] for c in cards]


async def test_choosing_a_book_screening_and_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ids = await seed(db_session)
    await login(client)

    overview = await get(client, "/vocab")
    assert overview["book_id"] is None and len(overview["books"]) == 9
    assert book(overview, "cet4") == {
        "id": "cet4",
        "name_zh": "大学英语四级",
        "name_en": "CET-4",
        "total": 5,
        "learning": 0,
        "known": 0,
    }
    assert overview["today"] == {"reviews_due": 0, "new_left": 0, "new_limit": 15, "new_started": 0}
    response = await client.get("/vocab/screen")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "no_book"
    response = await client.put("/vocab/book", json={"book_id": "nope"})
    assert response.status_code == 404 and response.json()["detail"]["code"] == "book_not_found"

    await choose(client, "cet4", daily_new=3)
    overview = await get(client, "/vocab")
    assert (overview["book_id"], overview["daily_new"], overview["screened"]) == ("cet4", 3, False)
    assert overview["today"]["new_left"] == 3

    batch = (await get(client, "/vocab/screen"))["words"]
    assert spelled([{"word": w} for w in batch]) == ["common", "middle", "less", "rarer", "rarest"]
    response = await client.post(
        "/vocab/screen", json={"shown": [ids["common"]], "known": [ids["gre1"]]}
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "not_in_batch"
    shown = [w["id"] for w in batch]
    response = await client.post(
        "/vocab/screen", json={"shown": shown, "known": [ids["common"], ids["middle"]]}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"known": 2, "shown": 5, "skipped_ahead": False}

    overview = await get(client, "/vocab")
    assert overview["screened"] is True
    assert (book(overview, "cet4")["known"], book(overview, "cet4")["learning"]) == (2, 0)
    # The book is used up; unticked words come as new words instead.
    assert (await get(client, "/vocab/screen"))["words"] == []
    queue = await get(client, "/vocab/queue")
    assert spelled(queue["new"]) == ["less", "rarer", "rarest"]

    # Switching keeps every card; screening starts over in the new book.
    await choose(client, "gre")
    overview = await get(client, "/vocab")
    assert (overview["book_id"], overview["daily_new"], overview["screened"]) == (
        "gre",
        None,
        False,
    )
    assert book(overview, "cet4")["known"] == 2


async def test_reviewing_the_daily_queue(client: AsyncClient, db_session: AsyncSession) -> None:
    ids = await seed(db_session)
    await login(client)
    await choose(client, "cet4", daily_new=2)

    queue = await get(client, "/vocab/queue", tz="Asia/Shanghai")
    assert queue["reviews"] == [] and spelled(queue["new"]) == ["common", "middle"]
    assert queue["new"][0]["status"] is None and queue["new"][0]["word"]["translation"]

    response = await client.post(
        "/vocab/reviews", json={"word_id": ids["common"], "rating": 1, "duration_ms": 4200}
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert (card["status"], card["source"]) == ("learning", "book") and card["due"]

    # Failed a minute ago, it is due again within the learn-ahead window.
    queue = await get(client, "/vocab/queue", tz="not/a-zone")
    assert spelled(queue["reviews"]) == ["common"] and spelled(queue["new"]) == ["middle"]
    assert (queue["reviews_due"], queue["new_started"]) == (1, 1)
    queue = await get(client, "/vocab/queue", mode="new")
    assert queue["reviews"] == [] and queue["reviews_due"] == 1
    overview = await get(client, "/vocab")
    assert overview["today"] == {"reviews_due": 1, "new_left": 1, "new_limit": 2, "new_started": 1}
    assert book(overview, "cet4")["learning"] == 1

    for body, code in [
        ({"word_id": ids["common"], "rating": 5}, "validation_error"),
        ({"word_id": 999_999, "rating": 3}, "word_not_found"),
    ]:
        response = await client.post("/vocab/reviews", json=body)
        assert response.json()["detail"]["code"] == code


async def test_the_own_word_list(client: AsyncClient, db_session: AsyncSession) -> None:
    ids = await seed(db_session)
    await login(client)
    await choose(client, "cet4")

    async def add(text: str) -> tuple[int, dict[str, Any]]:
        response = await client.post("/vocab/mine", json={"word": text})
        return response.status_code, response.json()

    status, body = await add(" went ")
    assert status == 201 and (body["card"]["word"]["word"], body["matched"]) == ("go", "lemma")
    assert (body["card"]["source"], body["card"]["status"], body["added"]) == (
        "manual",
        "new",
        True,
    )
    status, body = await add("Us")  # "US" and "us" both match; the more frequent wins
    assert (status, body["card"]["word"]["word"], body["matched"]) == (201, "us", "case")
    status, body = await add("go")
    assert (status, body["matched"], body["added"]) == (200, "exact", False)
    status, body = await add("wented")
    assert status == 404 and body["detail"]["code"] == "word_not_found"

    # A book word marked known joins the list as new; one being learned keeps its schedule.
    await client.post(
        "/vocab/screen", json={"shown": [ids["common"], ids["middle"]], "known": [ids["common"]]}
    )
    await client.post("/vocab/reviews", json={"word_id": ids["middle"], "rating": 3})
    status, body = await add("common")
    assert (status, body["card"]["status"], body["card"]["source"]) == (201, "new", "manual")
    status, body = await add("middle")
    assert (status, body["card"]["status"]) == (201, "learning")

    page = await get(client, "/vocab/mine")
    assert page["total"] == 4 and spelled(page["words"]) == ["middle", "common", "us", "go"]
    page = await get(client, "/vocab/mine", limit=1, offset=1)
    assert spelled(page["words"]) == ["common"]
    # Own words come before book words.
    assert spelled((await get(client, "/vocab/queue"))["new"])[:3] == ["go", "us", "common"]

    assert [w["word"] for w in await get(client, "/vocab/words", q="U")] == ["us", "US"]
    assert [w["word"] for w in await get(client, "/vocab/words", q="100%")] == ["100%_pure"]
    assert await get(client, "/vocab/words", q="%") == []

    # Removing really deletes the card and its reviews.
    response = await client.delete(f"/vocab/mine/{ids['middle']}")
    assert response.status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(ReviewLog)) == 0
    response = await client.delete(f"/vocab/mine/{ids['middle']}")
    assert response.status_code == 404
    # Book cards are not on the list.
    await client.post("/vocab/reviews", json={"word_id": ids["less"], "rating": 3})
    response = await client.delete(f"/vocab/mine/{ids['less']}")
    assert response.status_code == 404

    # Another learner sees none of it.
    await login(client, "other@example.com")
    assert (await get(client, "/vocab/mine"))["total"] == 0
    response = await client.delete(f"/vocab/mine/{ids['go']}")
    assert response.status_code == 404
    await switch_to(client, "learner@example.com")
    cards = await db_session.scalar(select(func.count()).select_from(UserCard))
    assert cards == 4  # go, us, common, less
