"""Generating and reading the cached advice (P1 plan §7.5.2)."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice import writer
from app.advice.service import Advice, AdviceRefresher, Locale, read
from app.advice.writer import AdviceDraft, DraftItem, Item
from app.db.models import UserProfile, UserWordBook
from app.db.session import create_sessionmaker
from tests.integration.test_advice_candidates import placement
from tests.integration.test_dashboard import new_user

RULES = get_rules()
CATALOG = get_grammar_catalog()
UTC_ZONE = ZoneInfo("UTC")


class FakeAdvisor:
    """Stands in for the `advice` route."""

    def __init__(self) -> None:
        self.drafts: list[AdviceDraft] = []
        self.prompts: list[str] = []
        self.configs: list[RunnableConfig | None] = []
        self.fail = False

    def get_structured_llm(self, ctx: Any, task: str, schema: type) -> Runnable[Any, Any]:
        assert task == "advice" and schema is AdviceDraft

        async def run(messages: list[BaseMessage], config: RunnableConfig | None = None) -> Any:
            if self.fail:
                raise RuntimeError("model glitch")
            self.prompts.append(str(messages[-1].content))
            self.configs.append(config)
            return self.drafts.pop(0) if self.drafts else AdviceDraft(items=[])

        return RunnableLambda(run)


def draft(*ids: str) -> AdviceDraft:
    return AdviceDraft(
        items=[DraftItem(candidate_id=i, title=f"Do {i}", reason=f"Why {i}") for i in ids]
    )


@pytest.fixture
def advisor(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAdvisor]:
    fake = FakeAdvisor()
    monkeypatch.setattr(writer, "get_structured_llm", fake.get_structured_llm)
    yield fake


@pytest.fixture
def refresher(db_engine: AsyncEngine) -> AdviceRefresher:
    return AdviceRefresher(create_sessionmaker(db_engine))


async def advice(
    session: AsyncSession, user_id: uuid.UUID, locale: Locale = "en", now: datetime | None = None
) -> Advice:
    session.expire_all()
    return await read(
        session, user_id, rules=RULES, catalog=CATALOG, tz=UTC_ZONE, locale=locale, now=now
    )


def ids(a: Advice) -> list[tuple[str, bool]]:
    """Each item's candidate and whether the model wrote it."""
    return [(item.candidate_id, item.title is not None) for item, _ in a.items]


async def test_templates_first_then_the_models_advice(
    db_session: AsyncSession, advisor: FakeAdvisor, refresher: AdviceRefresher
) -> None:
    user_id, tenant_id = await new_user(db_session)
    db_session.add(UserProfile(user_id=user_id, goal="Pass IELTS"))
    await db_session.commit()

    before = await advice(db_session, user_id)
    assert before.stale and before.status is None and before.generated_at is None
    assert ids(before) == [("placement", False), ("choose_book", False)]

    advisor.drafts.append(draft("choose_book", "made_up"))
    status = await refresher.generate(user_id, tenant_id, tz=UTC_ZONE, locale="zh-CN")

    assert status == "ai"
    assert "Write in: Simplified Chinese" in advisor.prompts[0]
    assert "- Goal: Pass IELTS" in advisor.prompts[0]
    config = advisor.configs[0]
    assert config is not None and config.get("metadata") == {"user_id": str(user_id)}
    after = await advice(db_session, user_id, "zh-CN")
    assert not after.stale and after.status == "ai" and after.generated_at is not None
    # The model's pick first, the invented id dropped, the other candidate as a template.
    assert ids(after) == [("choose_book", True), ("placement", False)]
    item, candidate = after.items[0]
    assert item == Item("choose_book", "Do choose_book", "Why choose_book")
    assert candidate.kind == "choose_book"
    # Read in English, the Chinese text is not shown, and it is due for regeneration.
    english = await advice(db_session, user_id, "en", now=datetime.now(UTC) + timedelta(hours=1))
    assert english.stale and ids(english) == [("placement", False), ("choose_book", False)]


async def test_done_work_disappears_at_once(
    db_session: AsyncSession, advisor: FakeAdvisor, refresher: AdviceRefresher
) -> None:
    user_id, tenant_id = await new_user(db_session)
    await db_session.commit()
    advisor.drafts.append(draft("choose_book", "placement"))
    await refresher.generate(user_id, tenant_id, tz=UTC_ZONE, locale="en")

    db_session.add(UserWordBook(user_id=user_id, book_id="cet4"))
    await db_session.commit()

    now = await advice(db_session, user_id)
    # choose_book is gone; screening the new book fills in as a template. Regeneration
    # waits a few minutes, in case the candidates change again.
    assert ids(now) == [("placement", True), ("vocab_screen", False)]
    assert not now.stale
    assert (await advice(db_session, user_id, now=datetime.now(UTC) + timedelta(minutes=11))).stale


async def test_no_model_or_a_failed_call_leaves_templates(
    db_session: AsyncSession, refresher: AdviceRefresher, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, tenant_id = await new_user(db_session)
    await db_session.commit()

    # The tenant has no connection: the real provider layer says so.
    assert await refresher.generate(user_id, tenant_id, tz=UTC_ZONE, locale="en") == "no_model"
    a = await advice(db_session, user_id)
    assert a.status == "no_model" and not a.stale
    assert ids(a) == [("placement", False), ("choose_book", False)]

    fake = FakeAdvisor()
    fake.fail = True
    monkeypatch.setattr(writer, "get_structured_llm", fake.get_structured_llm)
    assert await refresher.generate(user_id, tenant_id, tz=UTC_ZONE, locale="en") == "failed"
    assert (await advice(db_session, user_id)).status == "failed"


async def test_nothing_to_suggest_calls_no_model(
    db_session: AsyncSession, advisor: FakeAdvisor, refresher: AdviceRefresher
) -> None:
    user_id, tenant_id = await new_user(db_session)
    # Tested lately, book chosen and screened, nothing due, no new words left.
    db_session.add(UserWordBook(user_id=user_id, book_id="cet4", screen_offset=50))
    db_session.add(placement(user_id, datetime.now(UTC) - timedelta(days=1)))
    await db_session.commit()

    status = await refresher.generate(user_id, tenant_id, tz=UTC_ZONE, locale="en", by_hand=True)

    assert status == "empty" and advisor.prompts == []
    a = await advice(db_session, user_id)
    assert a.items == [] and not a.stale
    assert a.by_hand_after is not None


async def test_scheduled_once_per_learner(
    db_session: AsyncSession, advisor: FakeAdvisor, refresher: AdviceRefresher
) -> None:
    user_id, tenant_id = await new_user(db_session)
    await db_session.commit()

    refresher.schedule(user_id, tenant_id, tz=UTC_ZONE, locale="en")
    refresher.schedule(user_id, tenant_id, tz=UTC_ZONE, locale="en")
    assert refresher.is_busy(user_id)
    await refresher.wait_idle()

    assert not refresher.is_busy(user_id) and len(advisor.prompts) == 1
    assert (await advice(db_session, user_id)).status == "ai"
