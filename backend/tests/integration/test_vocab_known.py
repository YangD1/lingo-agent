"""/vocab/cards/{id}/known and /vocab/known: marking words known from a card (task 120)."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserCard
from tests.integration.test_chat_send import login
from tests.integration.test_learner_api import switch_to
from tests.integration.test_vocab_api import choose, get, seed, spelled


async def card(session: AsyncSession, word_id: int) -> UserCard | None:
    return await session.scalar(
        select(UserCard)
        .where(UserCard.word_id == word_id)
        .execution_options(populate_existing=True)
    )


async def test_marking_known_and_adding_back(client: AsyncClient, db_session: AsyncSession) -> None:
    ids = await seed(db_session)
    await login(client)
    await choose(client, "cet4", daily_new=5)

    async def mark(word: str) -> None:
        response = await client.post(f"/vocab/cards/{ids[word]}/known")
        assert response.status_code == 204, response.text

    async def unmark(word: str) -> None:
        response = await client.delete(f"/vocab/cards/{ids[word]}/known")
        assert response.status_code == 204, response.text

    # Screened known first, so it is the oldest on the known list.
    await client.post("/vocab/screen", json={"shown": [ids["less"]], "known": [ids["less"]]})
    # Failed a moment ago, so due now.
    await client.post("/vocab/reviews", json={"word_id": ids["common"], "rating": 1})
    learned = await card(db_session, ids["common"])
    assert learned is not None
    stability, difficulty = learned.stability, learned.difficulty
    queue = await get(client, "/vocab/queue")
    assert spelled(queue["reviews"]) == ["common"]

    # A word being learned and a book word never met both leave the queue.
    await mark("common")
    await mark("middle")
    await mark("middle")  # idempotent
    queue = await get(client, "/vocab/queue")
    assert queue["reviews"] == [] and queue["reviews_due"] == 0
    assert spelled(queue["new"]) == ["rarer", "rarest"]
    learned = await card(db_session, ids["common"])
    assert learned is not None and learned.status == "known"
    assert (learned.stability, learned.difficulty) == (stability, difficulty)
    met = await card(db_session, ids["middle"])
    assert met is not None and (met.source, met.status, met.state) == ("book", "known", None)

    response = await client.post("/vocab/cards/999999/known")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "word_not_found"

    # Every known word, most recently marked first, whatever marked it.
    page = await get(client, "/vocab/known")
    assert page["total"] == 3 and spelled(page["words"]) == ["middle", "common", "less"]
    assert [(w["source"], w["status"]) for w in page["words"]] == [("book", "known")] * 3
    assert page["words"][1]["last_review"] is not None
    page = await get(client, "/vocab/known", limit=1, offset=1)
    assert page["total"] == 3 and spelled(page["words"]) == ["common"]
    page = await get(client, "/vocab/known", q=" MI ")
    assert page["total"] == 1 and spelled(page["words"]) == ["middle"]
    assert (await get(client, "/vocab/known", q="%"))["total"] == 0

    # Added back: a reviewed word is due now with its schedule kept; a book word never
    # reviewed is unseen again and comes in book order.
    before = datetime.now(UTC)
    await unmark("common")
    await unmark("middle")
    await unmark("middle")  # idempotent
    await unmark("rarer")  # no card: nothing to do
    learned = await card(db_session, ids["common"])
    assert learned is not None and learned.status == "learning" and learned.due is not None
    assert before - timedelta(seconds=5) <= learned.due <= datetime.now(UTC)
    assert (learned.stability, learned.difficulty) == (stability, difficulty)
    assert await card(db_session, ids["middle"]) is None
    assert await card(db_session, ids["rarer"]) is None
    queue = await get(client, "/vocab/queue")
    assert spelled(queue["reviews"]) == ["common"]
    assert spelled(queue["new"]) == ["middle", "rarer", "rarest"]
    assert spelled((await get(client, "/vocab/known"))["words"]) == ["less"]


async def test_an_own_word_comes_back_new(client: AsyncClient, db_session: AsyncSession) -> None:
    ids = await seed(db_session)
    await login(client)
    await choose(client, "cet4")
    await client.post("/vocab/mine", json={"word": "go"})

    await client.post(f"/vocab/cards/{ids['go']}/known")
    assert "go" not in spelled((await get(client, "/vocab/queue"))["new"])
    assert spelled((await get(client, "/vocab/mine"))["words"]) == ["go"]

    await client.delete(f"/vocab/cards/{ids['go']}/known")
    own = await card(db_session, ids["go"])
    assert own is not None and (own.source, own.status) == ("manual", "new")
    assert spelled((await get(client, "/vocab/queue"))["new"])[0] == "go"


async def test_only_your_own_cards(client: AsyncClient, db_session: AsyncSession) -> None:
    ids = await seed(db_session)
    await login(client)
    await client.post(f"/vocab/cards/{ids['common']}/known")

    await login(client, "other@example.com")
    assert (await get(client, "/vocab/known"))["total"] == 0
    response = await client.delete(f"/vocab/cards/{ids['common']}/known")
    assert response.status_code == 204
    await client.post(f"/vocab/cards/{ids['middle']}/known")

    await switch_to(client, "learner@example.com")
    assert spelled((await get(client, "/vocab/known"))["words"]) == ["common"]
