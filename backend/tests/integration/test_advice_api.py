"""`GET /advice`: the learning engine's candidates, no model (ADR 0016 §3)."""

from httpx import AsyncClient

from tests.integration.test_chat_send import connect, login
from tests.integration.test_learner_api import switch_to


async def test_candidates_best_first_without_a_model(client: AsyncClient) -> None:
    await login(client)

    response = await client.get("/advice", params={"tz": "Asia/Shanghai"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_ready"] is False
    assert [i["kind"] for i in body["items"]] == ["placement", "choose_book"]
    placement = body["items"][0]
    assert placement["days_since"] is None and placement["in_progress"] is False
    assert placement["candidate_id"] == "placement"


async def test_live_evidence_and_model_ready(client: AsyncClient) -> None:
    await login(client)
    await connect(client, "deepseek")
    response = await client.put("/vocab/book", json={"book_id": "cet4"})
    assert response.status_code == 204, response.text

    body = (await client.get("/advice")).json()

    assert body["model_ready"] is True
    screen = next(i for i in body["items"] if i["kind"] == "vocab_screen")
    assert screen["book"] == {"id": "cet4", "name_en": "CET-4", "name_zh": "大学英语四级"}


async def test_advice_is_the_learners_own(client: AsyncClient) -> None:
    await login(client, "first@example.com")
    assert (await client.put("/vocab/book", json={"book_id": "cet4"})).status_code == 204
    await login(client, "second@example.com")

    kinds = [i["kind"] for i in (await client.get("/advice")).json()["items"]]
    assert "choose_book" in kinds and "vocab_screen" not in kinds

    await switch_to(client, "first@example.com")
    kinds = [i["kind"] for i in (await client.get("/advice")).json()["items"]]
    assert "vocab_screen" in kinds and "choose_book" not in kinds


async def test_needs_login(client: AsyncClient) -> None:
    assert (await client.get("/advice")).status_code == 401
