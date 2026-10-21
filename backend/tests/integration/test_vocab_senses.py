"""English senses and untranslated sentences on flashcards (ADR 0062, task 121)."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WordSense, WordSentence
from tests.integration.test_chat_send import login
from tests.integration.test_vocab_api import choose, get, seed, spelled


async def test_cards_carry_senses_in_dictionary_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ids = await seed(db_session)
    db_session.add_all(
        [
            WordSense(
                word_id=ids["common"],
                source="simplewiktionary",
                rank=1,
                pos="noun",
                gloss="A common is an area shared by many people.",
                source_title="common",
            ),
            WordSense(
                word_id=ids["common"],
                source="simplewiktionary",
                rank=0,
                pos="adjective",
                gloss="Mutual; shared by more than one.",
                labels=["countable"],
                examples=["The two teams have a common goal."],
                synonyms=["mutual", "shared"],
                source_title="common",
            ),
            WordSentence(
                word_id=ids["common"],
                source="tatoeba",
                rank=0,
                en="It is a common name.",
                zh=None,
                source_id="7",
            ),
        ]
    )
    await db_session.commit()
    await login(client)
    await choose(client, "cet4", daily_new=2)

    queue = await get(client, "/vocab/queue")
    assert spelled(queue["new"]) == ["common", "middle"]
    url = "https://simple.wiktionary.org/wiki/common"
    assert queue["new"][0]["senses"] == [
        {
            "pos": "adjective",
            "gloss": "Mutual; shared by more than one.",
            "labels": ["countable"],
            "examples": ["The two teams have a common goal."],
            "synonyms": ["mutual", "shared"],
            "source": "simplewiktionary",
            "url": url,
        },
        {
            "pos": "noun",
            "gloss": "A common is an area shared by many people.",
            "labels": [],
            "examples": [],
            "synonyms": [],
            "source": "simplewiktionary",
            "url": url,
        },
    ]
    # No Chinese translation: the sentence still comes, without one.
    assert queue["new"][0]["sentences"][0]["zh"] is None
    assert queue["new"][1]["senses"] == []

    response = await client.post("/vocab/reviews", json={"word_id": ids["common"], "rating": 3})
    assert response.status_code == 200, response.text
    assert [s["pos"] for s in response.json()["senses"]] == ["adjective", "noun"]

    await client.post(f"/vocab/cards/{ids['common']}/known")
    known = await get(client, "/vocab/known")
    assert len(known["words"][0]["senses"]) == 2
