"""Reviewing writing: evidence, mastery, words and the background worker (task 38.2)."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.exercise_graph import ModelReply, StructuredCall
from app.auth.service import register_user
from app.db.models import (
    KCEvidence,
    KCMastery,
    TenantMember,
    UserCard,
    UserProfile,
    Word,
    WritingSubmission,
)
from app.db.session import create_sessionmaker
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from app.writing import service
from app.writing.review import Review
from app.writing.worker import WritingWorker

KC = "g.past_simple_regular"
OTHER_KC = "g.be_present"
# Three sentences, 26 words: "walk" is wrong twice, "is" once.
TEXT = (
    "Yesterday I walk to the park with my friend.\n\n"
    "We walk around the lake for an hour.\n\n"
    "The weather are nice and we talk a lot."
)


@pytest.fixture
async def maker(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # db_session's teardown truncates the tables after the test.
    yield create_sessionmaker(db_engine)


async def learner(maker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        user = await register_user(session, f"{uuid.uuid4()}@example.com", "password123")
        tenant_id = await session.scalar(
            select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
        )
        await session.commit()
    assert tenant_id is not None
    return user.id, tenant_id


def mistake(kc_id: str, original: str) -> dict[str, Any]:
    return {
        "kc_id": kc_id,
        "error_type": "wrong_form",
        "severity": "medium",
        "original": original,
        "correction": "fixed",
        "explanation": "why",
    }


def a_review(vocab: Sequence[str] = ()) -> Review:
    score = {"score": 3, "reason": "ok"}
    return Review.model_validate(
        {
            "sentences": [
                {"index": 0, "corrected": "Yesterday I walked to the park with my friend.",
                 "mistakes": [mistake(KC, "walk")]},
                {"index": 1, "corrected": "We walked around the lake for an hour.",
                 "mistakes": [mistake(KC, "walk"), mistake("g.not_a_kc", "We")]},
                {"index": 2, "corrected": "The weather was nice and we talked a lot.",
                 "mistakes": [mistake(OTHER_KC, "are")]},
            ],
            "scores": dict.fromkeys(("task", "coherence", "vocabulary", "grammar"), score),
            "summary": "Good start.",
            "vocab_candidates": list(vocab),
        }
    )  # fmt: skip


class FakeReview:
    def __init__(self, output: Review | None = None, error: Exception | None = None) -> None:
        self.output = output or a_review()
        self.error = error
        self.calls: list[Sequence[BaseMessage]] = []
        self.gate: asyncio.Event | None = None
        self.called = asyncio.Event()

    async def __call__(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        assert schema is Review
        self.calls.append(messages)
        self.called.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return ModelReply(self.output, "conn:fake-model")


def worker(maker: async_sessionmaker[AsyncSession], fake: FakeReview) -> WritingWorker:
    def calls(ctx: TenantProviderContext, config: RunnableConfig) -> StructuredCall:
        assert config["metadata"]["user_id"]  # llm_usage knows whose call this is
        return fake

    return WritingWorker(maker, calls=calls)


async def submit(
    maker: async_sessionmaker[AsyncSession],
    writing: WritingWorker,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    text: str = TEXT,
) -> int:
    async with maker() as session:
        row = await service.create(session, user_id, text=text, prompt=" A day out ")
        await session.commit()
        submission_id = row.id
    writing.submit(submission_id, user_id, tenant_id)
    return submission_id


async def get(maker: async_sessionmaker[AsyncSession], submission_id: int) -> WritingSubmission:
    async with maker() as session:
        row = await session.get(WritingSubmission, submission_id)
        assert row is not None
        return row


async def test_a_review_is_stored_with_its_evidence_and_mastery(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)
    fake = FakeReview()
    writing = worker(maker, fake)

    submission_id = await submit(maker, writing, user_id, tenant_id)
    await writing.wait(submission_id)

    row = await get(maker, submission_id)
    assert (row.status, row.model, row.prompt, row.word_count) == (
        "done", "conn:fake-model", "A day out", 26,
    )  # fmt: skip
    assert row.reviewed_at is not None and row.summary == "Good start."
    assert [len(s["mistakes"]) for s in row.corrections or []] == [1, 1, 1]  # unknown KC dropped
    assert row.scores and row.scores["grammar"] == {"score": 3, "reason": "ok"}
    # The model saw numbered sentences at the default level, in Chinese.
    prompt = str(fake.calls[0][-1].content)
    assert (
        "[2] The weather are nice" in prompt and "A2" in prompt and "Simplified Chinese" in prompt
    )

    async with maker() as session:
        evidence = list(await session.scalars(select(KCEvidence).order_by(KCEvidence.id)))
        mastery = {m.kc_id: m for m in await session.scalars(select(KCMastery))}
    assert [(e.kc_id, e.source, e.evidence, e.correct, e.writing_id) for e in evidence] == [
        (KC, "writing", "production", False, submission_id),
        (KC, "writing", "production", False, submission_id),
        (OTHER_KC, "writing", "production", False, submission_id),
    ]
    # One piece of writing is one turn: "walk" twice counts once.
    assert mastery[KC].observations == 1
    assert mastery[OTHER_KC].observations == 1
    assert mastery[KC].last_mistake_at is not None


async def test_level_and_explanation_language_come_from_the_profile(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)
    async with maker() as session:
        profile = await session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if profile is None:
            profile = UserProfile(user_id=user_id)
            session.add(profile)
        profile.cefr_level, profile.explanation_language = "B2", "en"
        await session.commit()
    fake = FakeReview()
    writing = worker(maker, fake)

    await writing.wait(await submit(maker, writing, user_id, tenant_id))

    prompt = str(fake.calls[0][-1].content)
    assert "(CEFR): B2" in prompt and "in: English" in prompt


async def test_unknown_words_go_on_the_word_list(maker: async_sessionmaker[AsyncSession]) -> None:
    user_id, tenant_id = await learner(maker)
    async with maker() as session:
        lake = Word(word="lakeshore", translation="湖岸", tags=[], frq=1)
        stroll = Word(word="strollwalk", translation="散步", tags=[], frq=1)
        session.add_all([lake, stroll])
        await session.flush()
        session.add(UserCard(user_id=user_id, word_id=stroll.id, source="manual", status="new"))
        await session.commit()
    writing = worker(maker, FakeReview(a_review(["lakeshore", "strollwalk", "notaword"])))

    submission_id = await submit(maker, writing, user_id, tenant_id)
    await writing.wait(submission_id)

    row = await get(maker, submission_id)
    assert row.words == [
        {"word_id": lake.id, "word": "lakeshore", "added": True},
        {"word_id": stroll.id, "word": "strollwalk", "added": False},  # had a card already
    ]
    async with maker() as session:
        cards = {c.word_id: c.source for c in await session.scalars(select(UserCard))}
    assert cards == {lake.id: "auto", stroll.id: "manual"}


async def test_collecting_words_failing_keeps_the_review(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, tenant_id = await learner(maker)
    async with maker() as session:
        lake = Word(word="lakeshore", translation="湖岸", tags=[], frq=1)
        session.add(lake)
        await session.commit()

    async def broken(session: AsyncSession, user_id: uuid.UUID, words: Any, **_: Any) -> Any:
        # Gets as far as writing a card, then fails.
        session.add(UserCard(user_id=user_id, word_id=lake.id, source="auto", status="new"))
        await session.flush()
        raise RuntimeError("word list is down")

    monkeypatch.setattr(service.mine, "collect", broken)
    writing = worker(maker, FakeReview(a_review(["lakeshore"])))

    submission_id = await submit(maker, writing, user_id, tenant_id)
    await writing.wait(submission_id)

    # Words are saved with the review, never after it (the page stops polling once it
    # is done); when they fail, the review is kept without them.
    row = await get(maker, submission_id)
    assert (row.status, row.words) == ("done", None)
    assert row.summary
    async with maker() as session:
        assert list(await session.scalars(select(UserCard))) == []  # rolled back


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NoModelConfiguredError("llm", "writing_review", []), "no_llm_configured"),
        (RuntimeError("model said no"), "review_failed"),
    ],
)
async def test_a_failed_review_saves_nothing_but_the_status(
    maker: async_sessionmaker[AsyncSession], error: Exception, code: str
) -> None:
    user_id, tenant_id = await learner(maker)
    writing = worker(maker, FakeReview(error=error))

    submission_id = await submit(maker, writing, user_id, tenant_id)
    await writing.wait(submission_id)

    row = await get(maker, submission_id)
    assert (row.status, row.error_code, row.corrections) == ("failed", code, None)
    async with maker() as session:
        assert await session.scalar(select(KCEvidence.id)) is None


async def test_deleting_a_submission_takes_its_evidence(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)
    writing = worker(maker, FakeReview())
    submission_id = await submit(maker, writing, user_id, tenant_id)
    await writing.wait(submission_id)

    async with maker() as session:
        row = await session.get(WritingSubmission, submission_id)
        await session.delete(row)
        await session.commit()
        assert await session.scalar(select(KCEvidence.id)) is None


@pytest.mark.parametrize(
    ("text", "code"), [("Too short.", "too_short"), ("word " * 801, "too_long")]
)
async def test_length_is_checked_before_any_model_call(
    maker: async_sessionmaker[AsyncSession], text: str, code: str
) -> None:
    user_id, _ = await learner(maker)
    async with maker() as session:
        with pytest.raises(service.LengthError) as raised:
            await service.create(session, user_id, text=text)
    assert raised.value.code == code


async def test_stopping_marks_a_running_review_interrupted_and_recover_fails_leftovers(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, tenant_id = await learner(maker)
    fake = FakeReview()
    fake.gate = asyncio.Event()  # never set: the review hangs in the model call
    writing = worker(maker, fake)
    running = await submit(maker, writing, user_id, tenant_id)
    await fake.called.wait()

    await writing.stop()

    assert (await get(maker, running)).error_code == "interrupted"
    async with maker() as session:
        left = await service.create(session, user_id, text=TEXT)
        await session.commit()
    assert await WritingWorker(maker).recover() == 1
    row = await get(maker, left.id)
    assert (row.status, row.error_code) == ("failed", "interrupted")
