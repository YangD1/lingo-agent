"""`GET /advice` and `POST /advice/refresh` (P1 plan §7.5.2)."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.advice import writer
from app.advice.service import AdviceRefresher
from tests.integration.test_advice_service import FakeAdvisor, draft
from tests.integration.test_chat_send import login
from tests.integration.test_learner_api import switch_to


@pytest.fixture
def advisor(monkeypatch: pytest.MonkeyPatch) -> FakeAdvisor:
    fake = FakeAdvisor()
    monkeypatch.setattr(writer, "get_structured_llm", fake.get_structured_llm)
    return fake


@pytest.fixture
def refresher(app: FastAPI, advisor: FakeAdvisor) -> Iterator[AdviceRefresher]:
    refresher: AdviceRefresher = app.state.advice_refresher
    refresher.enabled = True
    yield refresher


async def test_templates_at_once_then_the_model_writes_in_the_background(
    client: AsyncClient, advisor: FakeAdvisor, refresher: AdviceRefresher
) -> None:
    await login(client)
    advisor.drafts.append(draft("choose_book"))

    first = await client.get("/advice", params={"tz": "Asia/Shanghai", "locale": "zh-CN"})

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] is None and body["refreshing"] is True
    assert [(i["kind"], i["title"]) for i in body["items"]] == [
        ("placement", None),
        ("choose_book", None),
    ]
    placement = body["items"][0]
    assert placement["days_since"] is None and placement["in_progress"] is False

    await refresher.wait_idle()
    assert "Write in: Simplified Chinese" in advisor.prompts[0]
    second = (await client.get("/advice", params={"locale": "zh-CN"})).json()
    assert second["status"] == "ai" and second["refreshing"] is False
    assert second["generated_at"] is not None and second["refresh_after"] is None
    assert [(i["candidate_id"], i["title"]) for i in second["items"]] == [
        ("choose_book", "Do choose_book"),
        ("placement", None),
    ]
    # Fresh advice: nothing new is scheduled.
    assert len(advisor.prompts) == 1

    # The locale cookie decides when the page does not say.
    client.cookies.set("NEXT_LOCALE", "en")
    third = (await client.get("/advice")).json()
    assert [i["title"] for i in third["items"]] == [None, None]


async def test_live_evidence_comes_with_each_item(
    client: AsyncClient, advisor: FakeAdvisor, refresher: AdviceRefresher
) -> None:
    await login(client)
    response = await client.put("/vocab/book", json={"book_id": "cet4"})
    assert response.status_code == 204, response.text

    items = (await client.get("/advice")).json()["items"]

    screen = next(i for i in items if i["kind"] == "vocab_screen")
    assert screen["book"] == {"id": "cet4", "name_en": "CET-4", "name_zh": "大学英语四级"}
    await refresher.wait_idle()


async def test_refresh_by_hand_once_an_hour(
    client: AsyncClient, advisor: FakeAdvisor, refresher: AdviceRefresher
) -> None:
    await login(client)

    accepted = await client.post("/advice/refresh", params={"locale": "en"})
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["refreshing"] is True
    await refresher.wait_idle()

    limited = await client.post("/advice/refresh")
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "advice_refresh_limited"
    assert 3500 < int(limited.headers["retry-after"]) <= 3600
    assert (await client.get("/advice")).json()["refresh_after"] is not None


async def test_advice_is_the_learners_own(
    client: AsyncClient, advisor: FakeAdvisor, refresher: AdviceRefresher
) -> None:
    await login(client, "first@example.com")
    await login(client, "second@example.com")
    await switch_to(client, "first@example.com")
    advisor.drafts.append(draft("placement"))
    await client.get("/advice")
    await refresher.wait_idle()
    assert (await client.get("/advice")).json()["items"][0]["title"] == "Do placement"

    await switch_to(client, "second@example.com")
    other = (await client.get("/advice")).json()
    assert other["status"] is None and all(i["title"] is None for i in other["items"])
    await refresher.wait_idle()


async def test_needs_login(client: AsyncClient) -> None:
    assert (await client.get("/advice")).status_code == 401
