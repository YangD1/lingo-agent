"""Shadowing: assessment or transcript comparison, kept attempts, evidence (task 56.3)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import get_rules
from app.db.models import (
    KCEvidence,
    PronunciationAttempt,
    SkillEstimate,
    UserProfile,
    Word,
    WordPronunciation,
)
from app.providers import pronunciation
from app.providers.asr import Transcript, TranscriptionError
from app.providers.config import RouteSpec
from app.providers.errors import NoModelConfiguredError
from app.services.speech import shadowing
from app.services.speech.shadowing import ShadowingError, shadow
from tests.integration.test_reading_versions import login
from tests.unit.provider_fixtures import conn, make_ctx
from tests.unit.test_pronunciation import wav

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
SENTENCE = "Good morning, everyone."
RULES = get_rules()


def azure_result(
    *,
    overall: float = 80.0,
    completeness: float = 100.0,
    words: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "RecognitionStatus": "Success",
        "NBest": [
            {
                "Display": "Good morning everyone.",
                "AccuracyScore": overall,
                "FluencyScore": overall,
                "CompletenessScore": completeness,
                "PronScore": overall,
                "Words": words
                if words is not None
                else [
                    {"Word": "good", "AccuracyScore": 95.0, "ErrorType": "None"},
                    {"Word": "morning", "AccuracyScore": 40.0, "ErrorType": "Mispronunciation"},
                    {"Word": "everyone", "AccuracyScore": 85.0, "ErrorType": "None"},
                ],
            }
        ],
    }


class Azure:
    def __init__(self) -> None:
        self.responses: list[httpx2.Response] = []
        self.calls = 0

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        return self.responses.pop(0)


@pytest.fixture
def azure(monkeypatch: pytest.MonkeyPatch) -> Azure:
    fake = Azure()

    def client(*, allow_private: bool, timeout: float | None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handle))

    monkeypatch.setattr(pronunciation, "make_async_http_client", client)
    return fake


@dataclass(frozen=True)
class FakeSpeechToText:
    text: str | None  # None: the vendor fails
    task: str = "asr"

    async def transcribe(self, audio: bytes, **_: Any) -> Transcript:
        if self.text is None:
            raise TranscriptionError("down")
        return Transcript(self.text)


def stt(monkeypatch: pytest.MonkeyPatch, text: str | None) -> list[str]:
    """Speech-to-text answering `text`; returns the tasks it was asked under."""
    tasks: list[str] = []

    def get_asr(ctx: Any) -> FakeSpeechToText:
        return FakeSpeechToText(text)

    original = shadowing.dataclasses.replace

    def replace(obj: Any, **changes: Any) -> Any:
        tasks.append(changes.get("task", ""))
        return original(obj, **changes)

    monkeypatch.setattr(shadowing, "get_asr", get_asr)
    monkeypatch.setattr(shadowing.dataclasses, "replace", replace)
    return tasks


def no_asr(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_asr(ctx: Any) -> Any:
        raise NoModelConfiguredError("asr", "default", [])

    monkeypatch.setattr(shadowing, "get_asr", get_asr)


def ctx(*, assess: bool = True) -> Any:
    """With an Azure connection on the pronunciation route, or no connection at all (the
    YAML's default route would pick up any connection named "azure")."""
    if not assess:
        return make_ctx(conn("openai"))
    return make_ctx(
        conn("azure", "azure_speech", base_url="https://eastasia.tts.speech.microsoft.com"),
        routes={("pronunciation", "default"): RouteSpec(models=["azure:pronunciation"])},
    )


@pytest.fixture
async def user(client: AsyncClient, db_session: AsyncSession) -> uuid.UUID:
    user_id = await login(client)
    db_session.add_all(
        [
            Word(word="good", translation="好", frq=100),
            Word(word="morning", translation="早上", frq=800),
            Word(word="everyone", translation="每个人", frq=2500),
        ]
    )
    await db_session.commit()
    return user_id


async def run(db_session: AsyncSession, user_id: uuid.UUID, **kw: Any) -> shadowing.Outcome:
    args: dict[str, Any] = {
        "ctx": ctx(),
        "audio": wav(2.0),
        "reference_text": SENTENCE,
        "language": "en-US",
        "source": "chat",
        "source_id": "m1",
    } | kw
    return await shadow(db_session, user_id=user_id, rules=RULES, now=NOW, **args)


async def speaking(db_session: AsyncSession, user_id: uuid.UUID) -> SkillEstimate | None:
    return await db_session.scalar(
        select(SkillEstimate).where(
            SkillEstimate.user_id == user_id, SkillEstimate.skill == "speaking"
        ),
        execution_options={"populate_existing": True},
    )


def test_sentence_difficulty_from_rarest_word_and_length() -> None:
    anchor = RULES.difficulty.cefr_anchor
    # Rarest rank 2500 is B1 (past A2's 2000); 3 words is a short sentence (-0.3).
    assert shadowing.sentence_difficulty([100, 2500], 3, RULES) == anchor["B1"] - 0.3
    # A word with no rank is rare: C2. Long sentence: +0.3.
    assert shadowing.sentence_difficulty([None], 20, RULES) == anchor["C2"] + 0.3
    assert shadowing.sentence_difficulty([], 8, RULES) == anchor["A1"]


async def test_an_assessment_is_kept_and_counts_as_evidence(
    db_session: AsyncSession, user: uuid.UUID, azure: Azure
) -> None:
    azure.responses = [httpx2.Response(200, json=azure_result(overall=80))]

    outcome = await run(db_session, user)

    attempt = outcome.attempt
    assert (attempt.provider, attempt.counted, attempt.fallback_reason) == ("azure", True, None)
    assert attempt.scores is not None and attempt.scores["overall"] == 80
    assert [w["word"] for w in attempt.words] == ["good", "morning", "everyone"]
    assert (attempt.source, attempt.source_id, attempt.audio_seconds) == ("chat", "m1", 2.0)
    assert outcome.mispronounced == ("morning",)

    # Speaking starts at the default level's anchor (no placement) and moves up: 0.8 beats
    # the expected chance against this easy sentence's difficulty.
    ability = await speaking(db_session, user)
    assert ability is not None and ability.attempts == 1
    start = RULES.difficulty.cefr_anchor[RULES.practice.default_level]
    assert ability.rating > start

    marks = {
        w.word_id: w
        for w in await db_session.scalars(
            select(WordPronunciation).where(WordPronunciation.user_id == user)
        )
    }
    assert sorted(m.accuracy for m in marks.values()) == [40.0, 85.0, 95.0]
    assert sum(m.low_count for m in marks.values()) == 1
    # Never grammar evidence.
    assert list(await db_session.scalars(select(KCEvidence))) == []


async def test_a_later_good_reading_clears_the_mark(
    db_session: AsyncSession, user: uuid.UUID, azure: Azure
) -> None:
    good = [{"Word": "morning", "AccuracyScore": 90.0, "ErrorType": "None"}]
    azure.responses = [
        httpx2.Response(200, json=azure_result()),
        httpx2.Response(200, json=azure_result(words=good)),
    ]
    await run(db_session, user)

    outcome = await run(db_session, user, reference_text="Morning!")

    assert outcome.mispronounced == ()
    morning = await db_session.scalar(
        select(WordPronunciation)
        .join(Word, Word.id == WordPronunciation.word_id)
        .where(Word.word == "morning"),
        execution_options={"populate_existing": True},
    )
    assert morning is not None
    assert (morning.accuracy, morning.low_count, morning.last_low_at) == (90.0, 1, NOW)


@pytest.mark.parametrize(
    ("kw", "completeness"),
    [
        ({}, 40.0),  # barely read
        ({"reference_text": "Good morning."}, 100.0),  # fewer than 3 words
        ({"audio": wav(0.5)}, 100.0),  # too short a recording
    ],
)
async def test_attempts_that_say_little_do_not_move_ability(
    db_session: AsyncSession,
    user: uuid.UUID,
    azure: Azure,
    kw: dict[str, Any],
    completeness: float,
) -> None:
    azure.responses = [httpx2.Response(200, json=azure_result(completeness=completeness))]

    outcome = await run(db_session, user, **kw)

    assert (outcome.attempt.provider, outcome.attempt.counted) == ("azure", False)
    assert await speaking(db_session, user) is None
    # The words read still get their marks.
    assert outcome.mispronounced == ("morning",)


async def test_starts_from_the_placement_level(
    db_session: AsyncSession, user: uuid.UUID, azure: Azure
) -> None:
    profile = await db_session.scalar(select(UserProfile).where(UserProfile.user_id == user))
    if profile is None:
        profile = UserProfile(user_id=user)
        db_session.add(profile)
    profile.cefr_level = "C1"
    await db_session.commit()
    azure.responses = [httpx2.Response(200, json=azure_result(overall=30))]

    await run(db_session, user)

    ability = await speaking(db_session, user)
    assert ability is not None and ability.rating < RULES.difficulty.cefr_anchor["C1"]


async def test_without_assessment_the_transcript_is_compared(
    db_session: AsyncSession, user: uuid.UUID, azure: Azure, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = stt(monkeypatch, "good evening everyone")

    outcome = await run(db_session, user, ctx=ctx(assess=False))

    attempt = outcome.attempt
    assert (attempt.provider, attempt.fallback_reason, attempt.scores) == (
        "asr_fallback",
        "not_configured",
        None,
    )
    assert [(w["word"], w["status"]) for w in attempt.words] == [
        ("Good", "none"),
        ("morning", "substitution"),
        ("everyone", "none"),
    ]
    assert attempt.recognized_text == "good evening everyone"
    assert tasks == ["shadowing_asr"]
    # A rough result is never evidence.
    assert not attempt.counted and outcome.mispronounced == ()
    assert await speaking(db_session, user) is None
    assert list(await db_session.scalars(select(WordPronunciation))) == []
    assert azure.calls == 0


async def test_a_failed_assessment_falls_back_to_the_transcript(
    db_session: AsyncSession, user: uuid.UUID, azure: Azure, monkeypatch: pytest.MonkeyPatch
) -> None:
    azure.responses = [httpx2.Response(503, text="busy")]
    stt(monkeypatch, "good morning everyone")

    outcome = await run(db_session, user)

    assert (outcome.attempt.provider, outcome.attempt.fallback_reason) == (
        "asr_fallback",
        "failed",
    )


@pytest.mark.parametrize(
    ("assess", "azure_status", "code"),
    [
        (True, 503, "unavailable"),  # assessment failed, no speech-to-text
        (False, None, "not_configured"),  # neither configured
    ],
)
async def test_nothing_to_fall_back_on(
    db_session: AsyncSession,
    user: uuid.UUID,
    azure: Azure,
    monkeypatch: pytest.MonkeyPatch,
    assess: bool,
    azure_status: int | None,
    code: str,
) -> None:
    if azure_status is not None:
        azure.responses = [httpx2.Response(azure_status, text="busy")]
    no_asr(monkeypatch)

    with pytest.raises(ShadowingError) as info:
        await run(db_session, user, ctx=ctx(assess=assess))

    assert info.value.code == code
    assert list(await db_session.scalars(select(PronunciationAttempt))) == []


async def test_silence_bad_audio_and_failing_transcription(
    db_session: AsyncSession, user: uuid.UUID, azure: Azure, monkeypatch: pytest.MonkeyPatch
) -> None:
    azure.responses = [httpx2.Response(200, json={"RecognitionStatus": "InitialSilenceTimeout"})]
    with pytest.raises(ShadowingError) as info:
        await run(db_session, user)
    assert info.value.code == "no_speech"

    with pytest.raises(ShadowingError) as info:
        await run(db_session, user, audio=b"RIFF....WEBM")
    assert info.value.code == "invalid_audio"

    stt(monkeypatch, "...")
    with pytest.raises(ShadowingError) as info:
        await run(db_session, user, ctx=ctx(assess=False))
    assert info.value.code == "no_speech"

    stt(monkeypatch, None)
    with pytest.raises(ShadowingError) as info:
        await run(db_session, user, ctx=ctx(assess=False))
    assert info.value.code == "unavailable"
    assert list(await db_session.scalars(select(PronunciationAttempt))) == []
