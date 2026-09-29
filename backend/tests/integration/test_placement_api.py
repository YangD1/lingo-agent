"""Placement API (P1 plan §6.2): a whole test, leaving and coming back, retries."""

import asyncio
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.placement.items import get_item_bank
from app.adaptive.rules import get_rules
from app.db.models import KCEvidence, PlacementItemStat, UserProfile, Word
from tests.integration.test_chat_send import login
from tests.integration.test_learner_api import switch_to

BANK = get_item_bank()
# Seeded words of the first five bands, which the simulated learner knows.
KNOWN: set[str] = set()
QUESTION_KEYS = {"id", "stage", "index", "total", "word", "stem", "options"}


def letters(n: int) -> str:
    return "".join(chr(97 + int(d)) for d in str(n))


async def seed_words(db: AsyncSession, per_band: int = 3) -> None:
    """A few testable words in every band, plus an inflection that must never be asked."""
    vr = get_rules().placement.vocab
    words = [
        Word(
            word=f"w{letters(band)}q{letters(n)}",
            translation="释义",
            frq=band * vr.band_size + n + 1,
        )
        for band in range(vr.max_rank // vr.band_size)
        for n in range(per_band)
    ]
    KNOWN.update(w.word for w in words if w.frq is not None and w.frq <= 5 * vr.band_size)
    words.append(Word(word="went", translation="去", frq=2, exchange="0:go/1:p"))
    db.add_all(words)
    await db.commit()


async def post(client: AsyncClient, url: str, body: dict[str, Any], expect: int = 200) -> Any:
    response = await client.post(url, json=body)
    assert response.status_code == expect, response.text
    return response.json()


def reply(question: dict[str, Any], *, correct: bool = True) -> dict[str, Any]:
    assert set(question) <= QUESTION_KEYS
    if question["stage"] == "vocab":
        assert question["word"] != "went"
        # Knows every real word in the first few bands, and no pseudo-word.
        return {"question_id": question["id"], "yes": question["word"] in KNOWN}
    item = next(i for i in BANK.items if i.stem == question["stem"])
    wanted = item.answer if correct else item.distractors[0]
    return {"question_id": question["id"], "choice": question["options"].index(wanted)}


async def test_needs_the_word_list(client: AsyncClient) -> None:
    await login(client)
    body = await post(client, "/placement", {}, expect=409)
    assert body["detail"]["code"] == "words_not_imported"


async def test_a_whole_test(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_words(db_session)
    await login(client)
    assert (await client.get("/placement/latest")).json() is None

    state = await post(client, "/placement", {})
    assert state["status"] == "in_progress" and state["stage"] == "vocab"
    assert state["question"]["id"] == "vocab-0"
    session_id = state["id"]
    stages = []
    while state["status"] == "in_progress":
        question = state["question"]
        stages.append(question["stage"])
        state = await post(
            client,
            f"/placement/{session_id}/answer",
            reply(question, correct=question["index"] % 3 != 0),
        )
        assert state["answered"] == len(stages)

    assert stages[0] == "vocab" and stages[-1] == "grammar"
    assert state["status"] == "done" and state["question"] is None
    result = state["result"]
    assert set(result) == {"cefr", "vocab", "grammar"}  # no answers: they name the items
    assert result["cefr"] == result["grammar"]["cefr"]
    assert result["vocab"]["size"] > 0

    latest = (await client.get("/placement/latest")).json()
    assert latest["id"] == session_id and latest["status"] == "done"
    profile = await db_session.scalar(select(UserProfile))
    assert profile is not None and profile.cefr_level == result["cefr"]
    placed = await db_session.scalar(
        select(func.count()).select_from(KCEvidence).where(KCEvidence.source == "placement")
    )
    assert placed == result["grammar"]["answered"]
    assert await db_session.scalar(select(func.count()).select_from(PlacementItemStat)) == placed
    # The finished test's thread is gone; the result lives in the row.
    threads = await db_session.scalar(
        text("SELECT count(*) FROM checkpoints WHERE thread_id = :id"), {"id": session_id}
    )
    assert threads == 0

    # A new start after a finished test begins a new one.
    again = await post(client, "/placement", {})
    assert again["id"] != session_id and again["question"]["id"] == "vocab-0"


async def test_leave_and_come_back(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_words(db_session)
    await login(client)
    state = await post(client, "/placement", {})
    session_id = state["id"]
    for _ in range(3):
        state = await post(client, f"/placement/{session_id}/answer", reply(state["question"]))
    current = state["question"]
    assert current["id"] == "vocab-3"

    back = await post(client, "/placement", {})
    assert back["id"] == session_id and back["question"] == current
    fetched = (await client.get(f"/placement/{session_id}")).json()
    assert fetched["question"] == current and fetched["answered"] == 3


async def test_retries_and_bad_answers(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_words(db_session)
    await login(client)
    first = await post(client, "/placement", {})
    session_id, url = first["id"], f"/placement/{first['id']}/answer"
    second = await post(client, url, reply(first["question"]))

    # The same answer again (a retried request) changes nothing.
    retried = await post(client, url, reply(first["question"]))
    assert retried["question"] == second["question"] and retried["answered"] == 1

    ahead = await post(client, url, {"question_id": "vocab-7", "yes": True}, expect=409)
    assert ahead["detail"]["code"] == "stale_question"
    wrong_kind = await post(
        client, url, {"question_id": second["question"]["id"], "choice": 1}, expect=422
    )
    assert wrong_kind["detail"]["code"] == "invalid_answer"
    assert (await client.get(f"/placement/{session_id}")).json()["answered"] == 1


async def test_restart_abandons_the_running_test(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_words(db_session)
    await login(client)
    old = await post(client, "/placement", {})
    new = await post(client, "/placement", {"restart": True})
    assert new["id"] != old["id"] and new["question"]["id"] == "vocab-0"
    gone = (await client.get(f"/placement/{old['id']}")).json()
    assert gone["status"] == "abandoned" and gone["question"] is None
    body = await post(client, f"/placement/{old['id']}/answer", reply(old["question"]), expect=409)
    assert body["detail"]["code"] == "placement_not_in_progress"


async def test_someone_elses_test_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_words(db_session)
    await login(client, "owner@example.com")
    theirs = await post(client, "/placement", {})
    await login(client, "other@example.com")
    assert (await client.get(f"/placement/{theirs['id']}")).status_code == 404
    body = await post(
        client, f"/placement/{theirs['id']}/answer", reply(theirs["question"]), expect=404
    )
    assert body["detail"]["code"] == "placement_not_found"
    assert (await client.get("/placement/latest")).json() is None
    await switch_to(client, "owner@example.com")
    assert (await client.get("/placement/latest")).json()["id"] == theirs["id"]


async def test_the_same_answer_sent_twice_at_once_counts_once(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_words(db_session)
    await login(client)
    first = await post(client, "/placement", {})
    url = f"/placement/{first['id']}/answer"
    body = reply(first["question"])
    a, b = await asyncio.gather(client.post(url, json=body), client.post(url, json=body))
    assert (a.status_code, b.status_code) == (200, 200)
    assert a.json()["answered"] == b.json()["answered"] == 1
    assert a.json()["question"] == b.json()["question"]
