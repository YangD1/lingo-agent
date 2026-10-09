"""AI example sentences written ahead of time: the `word_examples_prefetch` job (task 44)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import ExamplesPrefetchRules, Rules, get_rules
from app.db.models import (
    Tenant,
    TenantMember,
    UserCard,
    UserProfile,
    UserWordBook,
    WordExample,
    WordSentence,
)
from app.scheduler import jobs, prefs
from app.scheduler.jobs import JobContext
from app.services.vocab import examples
from app.services.vocab.examples import Example, WordExamples
from app.services.vocab.prefetch import prefetch
from tests.integration.test_chat_send import connect
from tests.integration.test_vocab_api import seed

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


class FakeModel:
    """Stands in for get_structured_llm: one sentence using the prompt's word, or the
    result given for a word (an exception is raised)."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.results = results or {}
        self.words: list[str] = []
        self.configs: list[Any] = []

    def __call__(self, ctx: Any, task: str, schema: Any) -> "FakeModel":
        assert task == "word_examples"
        return self

    async def ainvoke(self, messages: list[Any], config: Any = None) -> WordExamples:
        prompt = str(messages[-1].content)
        word = prompt.split("\n", 1)[0].removeprefix("Word: ")
        self.words.append(word)
        self.configs.append(config)
        result = self.results.get(word)
        if isinstance(result, Exception):
            raise result
        return result or WordExamples(sentences=[Example(en=f"I like {word}.", zh="我喜欢。")])


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    fake = FakeModel()
    monkeypatch.setattr(examples, "get_structured_llm", fake)
    return fake


async def learner(
    client: AsyncClient, session: AsyncSession, *, model: bool = True
) -> tuple[uuid.UUID, uuid.UUID]:
    email = f"{uuid.uuid4()}@example.com"
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    user_id = uuid.UUID(response.json()["id"])
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    )
    assert tenant_id is not None
    if model:
        await connect(client, "deepseek")
    return user_id, tenant_id


def card(user_id: uuid.UUID, word_id: int, due: timedelta) -> UserCard:
    return UserCard(
        user_id=user_id,
        word_id=word_id,
        source="book",
        status="learning",
        state=2,
        stability=3.0,
        difficulty=5.0,
        due=NOW + due,
    )


async def setup(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """cet4 book, 2 new words a day; "common" has a real sentence; reviews of "go"
    (due in an hour) and "us" (in three days)."""
    ids = await seed(session)
    session.add(UserWordBook(user_id=user_id, book_id="cet4", daily_new=2))
    session.add(
        WordSentence(
            word_id=ids["common"],
            source="tatoeba",
            rank=0,
            en="It is common.",
            zh="很常见。",
            source_id="1",
        )
    )
    session.add_all(
        [card(user_id, ids["go"], timedelta(hours=1)), card(user_id, ids["us"], timedelta(days=3))]
    )
    await session.commit()
    return ids


def rules(per_learner: int = 30) -> Rules:
    base = get_rules()
    config = ExamplesPrefetchRules(ahead_hours=24, per_learner=per_learner)
    return base.model_copy(
        update={"vocab": base.vocab.model_copy(update={"examples_prefetch": config})}
    )


async def run(app: FastAPI, per_learner: int = 30) -> str | None:
    return await prefetch(app.state.sessionmaker, rules=rules(per_learner), now=NOW)


async def cached(session: AsyncSession) -> set[tuple[uuid.UUID, int, str]]:
    session.expire_all()
    rows = await session.execute(
        select(WordExample.tenant_id, WordExample.word_id, WordExample.cefr)
    )
    return {(t, w, c) for t, w, c in rows.all()}


async def test_writes_the_coming_words_without_real_sentences_once(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, model: FakeModel
) -> None:
    user_id, tenant_id = await learner(client, db_session)
    db_session.add(UserProfile(user_id=user_id, cefr_level="B2"))
    ids = await setup(db_session, user_id)

    assert await run(app) is None
    # The review due within a day, then tomorrow's new words; "common" has a real
    # sentence, "us" is not due for three days.
    assert model.words == ["go", "middle"]
    assert await cached(db_session) == {
        (tenant_id, ids["go"], "B2"),
        (tenant_id, ids["middle"], "B2"),
    }
    assert model.configs[0]["metadata"] == {"user_id": str(user_id), "background": True}

    assert await run(app) is None
    assert len(model.words) == 2  # cached now


async def test_through_the_scheduler_job(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, model: FakeModel
) -> None:
    user_id, tenant_id = await learner(client, db_session)
    ids = await setup(db_session, user_id)
    ctx = JobContext(app.state.sessionmaker, NOW, uuid.uuid4(), None)
    assert await jobs.word_examples_prefetch(ctx) is None
    # Not assessed: the button's default level.
    assert (tenant_id, ids["go"], "A2") in await cached(db_session)


async def test_at_most_per_learner_words(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, model: FakeModel
) -> None:
    user_id, _ = await learner(client, db_session)
    await setup(db_session, user_id)
    assert await run(app, per_learner=1) is None
    assert model.words == ["go"]


async def test_skips_learners_who_switched_it_off(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, model: FakeModel
) -> None:
    user_id, _ = await learner(client, db_session)
    await setup(db_session, user_id)
    await prefs.set_enabled(db_session, user_id, prefs.WORD_EXAMPLES_PREFETCH, False)
    await db_session.commit()
    assert await run(app) is None
    assert model.words == []


async def test_stops_at_the_budget(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, model: FakeModel
) -> None:
    user_id, tenant_id = await learner(client, db_session)
    await setup(db_session, user_id)
    await db_session.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(background_daily_tokens=0)
    )
    await db_session.commit()
    assert await run(app) == "budget_exhausted"
    assert model.words == []


async def test_no_model_writes_nothing(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    # The real get_structured_llm: no connection raises NoModelConfiguredError.
    user_id, _ = await learner(client, db_session, model=False)
    await setup(db_session, user_id)
    assert await run(app) is None
    assert await cached(db_session) == set()


async def test_invalid_sentences_are_skipped_and_errors_stop_the_tenant(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, model: FakeModel
) -> None:
    user_id, _ = await learner(client, db_session)
    ids = await setup(db_session, user_id)
    model.results = {
        "go": WordExamples(sentences=[Example(en="Nothing here.", zh="这里没有。")]),
        "middle": RuntimeError("vendor"),
    }
    await db_session.execute(
        update(UserWordBook).where(UserWordBook.user_id == user_id).values(daily_new=3)
    )
    await db_session.commit()

    assert await run(app) is None
    # "go" had no usable sentence and is left for later; the provider error on
    # "middle" stops the tenant before "less".
    assert model.words == ["go", "middle"]
    assert await cached(db_session) == set()
    assert "less" in ids


async def test_the_queue_shows_cached_sentences_without_calling(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, model: FakeModel
) -> None:
    user_id, _ = await learner(client, db_session)
    await setup(db_session, user_id)
    # Fixed `NOW`, not the wall clock: already past for the queue, and always inside
    # the prefetch window that `run` measures from `NOW`.
    await db_session.execute(update(UserCard).values(due=NOW))
    await db_session.commit()
    assert await run(app) is None
    calls = len(model.words)

    response = await client.get("/vocab/queue")
    assert response.status_code == 200, response.text
    cards = {c["word"]["word"]: c for c in [*response.json()["reviews"], *response.json()["new"]]}
    assert cards["go"]["ai_examples"] == [{"en": "I like go.", "zh": "我喜欢。"}]
    assert cards["us"]["ai_examples"] == [{"en": "I like us.", "zh": "我喜欢。"}]
    assert cards["common"]["ai_examples"] == []  # has a real sentence
    assert len(model.words) == calls
