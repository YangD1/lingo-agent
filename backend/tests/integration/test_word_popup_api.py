"""Looking up a word, AI example sentences and message translations (ADR 0017)."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import translate
from app.db.models import MessageTranslation, WordExample
from app.services.vocab import examples
from app.services.vocab.examples import Example, WordExamples
from tests.integration.test_chat_send import (
    connect,
    fake_models,
    history,
    login,
    new_conversation,
    send,
)
from tests.integration.test_vocab_api import seed


class FakeStructured:
    """Stands in for get_structured_llm: returns `result` (or raises it) and counts."""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self, ctx: Any, task: str, schema: Any) -> "FakeStructured":
        self.task = task
        return self

    async def ainvoke(self, messages: list[Any], config: Any = None) -> Any:
        self.calls += 1
        self.prompts.append(str(messages[-1].content))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_lookup_finds_the_lemma_and_whether_it_is_on_the_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed(db_session)
    await login(client)

    found = await client.get("/vocab/lookup", params={"word": "went"})
    assert found.status_code == 200, found.text
    body = found.json()
    assert (body["word"]["word"], body["matched"], body["on_list"]) == ("go", "lemma", False)
    assert body["word"]["translation"] == "go 释义"

    await client.post("/vocab/mine", json={"word": "go"})
    assert (await client.get("/vocab/lookup", params={"word": "go"})).json()["on_list"] is True

    missing = await client.get("/vocab/lookup", params={"word": "wented"})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "word_not_found"


async def test_examples_are_checked_cached_and_need_a_model(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await seed(db_session)
    await login(client)
    url = f"/vocab/words/{ids['go']}/examples"

    no_model = await client.post(url)
    assert no_model.status_code == 409 and no_model.json()["detail"]["code"] == "no_llm_configured"

    await connect(client, "deepseek")
    fake = FakeStructured(
        WordExamples(
            sentences=[
                Example(en="I go to school by bus.", zh="我坐公交上学。"),
                Example(en="She likes tea.", zh="她喜欢茶。"),  # doesn't use the word
            ]
        )
    )
    monkeypatch.setattr(examples, "get_structured_llm", fake)

    first = await client.post(url)
    assert first.status_code == 200, first.text
    assert first.json() == {
        "sentences": [{"en": "I go to school by bus.", "zh": "我坐公交上学。"}],
        "cefr": "A2",  # not assessed yet
    }
    assert fake.task == "word_examples" and "Word: go" in fake.prompts[0]
    again = await client.post(url)
    assert again.json() == first.json() and fake.calls == 1  # cached

    unknown = await client.post("/vocab/words/999999/examples")
    assert unknown.status_code == 404


async def test_examples_that_miss_the_word_or_fail_are_not_cached(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await seed(db_session)
    await login(client)
    await connect(client, "deepseek")
    url = f"/vocab/words/{ids['common']}/examples"

    monkeypatch.setattr(
        examples,
        "get_structured_llm",
        FakeStructured(WordExamples(sentences=[Example(en="Nothing here.", zh="这里没有。")])),
    )
    invalid = await client.post(url)
    assert invalid.status_code == 502 and invalid.json()["detail"]["code"] == "examples_invalid"

    monkeypatch.setattr(examples, "get_structured_llm", FakeStructured(RuntimeError("vendor")))
    down = await client.post(url)
    assert down.status_code == 502 and down.json()["detail"]["code"] == "llm_unavailable"
    assert await db_session.scalar(select(func.count()).select_from(WordExample)) == 0


async def test_a_tutor_message_is_translated_once(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_models(monkeypatch)
    await login(client)
    await connect(client, "deepseek")
    conversation = await new_conversation(client)
    await send(client, conversation, "Hi")
    learner, tutor = await history(client, conversation)
    fake = FakeStructured(translate.Translation(text="你好朋友"))
    monkeypatch.setattr(translate, "get_structured_llm", fake)

    url = f"/conversations/{conversation}/messages/{tutor['id']}/translate"
    first = await client.post(url, json={"target": "zh"})
    assert first.status_code == 200, first.text
    assert first.json() == {"message_id": tutor["id"], "target": "zh", "text": "你好朋友"}
    assert fake.task == "translate" and tutor["content"] in fake.prompts[0]
    assert "Simplified Chinese" in fake.prompts[0]
    assert (await client.post(url, json={"target": "zh"})).json() == first.json()
    assert fake.calls == 1  # kept

    # Only tutor messages, in your own conversations.
    own = f"/conversations/{conversation}/messages/{learner['id']}/translate"
    assert (await client.post(own, json={"target": "zh"})).status_code == 404
    bad = await client.post(url, json={"target": "fr"})
    assert bad.status_code == 422
    await client.post("/auth/logout")
    await login(client, "other@example.com")
    assert (await client.post(url, json={"target": "zh"})).status_code == 404

    # Deleting the conversation deletes its translations.
    await client.post("/auth/logout")
    await client.post(
        "/auth/login", json={"email": "learner@example.com", "password": "password123"}
    )
    assert (await client.delete(f"/conversations/{conversation}")).status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(MessageTranslation)) == 0
