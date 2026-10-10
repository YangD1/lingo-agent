"""Shadowing: a learner reads a sentence aloud after the model and gets it scored
(ADR 0028 §5-§6, task 56).

With a `pronunciation` route the recording is assessed (scores per sentence, word and
phoneme); without one, or when the assessment fails and speech-to-text is configured
(Q56e), it is transcribed and compared word by word (`alignment`), a rough result with
no scores. Every attempt is kept (Q56d); the recording is not.

Only an assessment is evidence (Q56b-c):
- speaking ability takes one Elo step, outcome = overall score / 100, against a
  sentence difficulty worked out from its length and rarest word - unless the attempt
  was barely read, too short, or of too few words;
- each lexicon word read gets its accuracy recorded, for the review card's "you don't
  say this one right" mark. Never grammar evidence.
"""

import dataclasses
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.elo import update_ability
from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel
from app.adaptive.rules import PronunciationRules, Rules
from app.attachments.handlers import heard_speech
from app.db.models import PronunciationAttempt, SkillEstimate, UserProfile, WordPronunciation
from app.providers.asr import TranscriptionError, get_asr
from app.providers.config import TenantProviderContext
from app.providers.errors import NoModelConfiguredError
from app.providers.pronunciation import (
    Assessment,
    AssessmentError,
    InvalidAudioError,
    Language,
    NoSpeechError,
    get_pronunciation,
    wav_seconds,
)
from app.services.reading import glossary
from app.services.speech.alignment import compare, words_of

SKILL = "speaking"
# llm_usage label of the transcript a rough result is compared from.
FALLBACK_TASK = "shadowing_asr"

type Source = Literal["chat", "reading", "vocab", "speaking"]
type ErrorCode = Literal["invalid_audio", "no_speech", "not_configured", "unavailable"]


class ShadowingError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Outcome:
    attempt: PronunciationAttempt
    # Lexicon words of the sentence the learner says wrong now, lowercase as read.
    mispronounced: tuple[str, ...] = ()


def level_of_rank(rank: int | None, rules: PronunciationRules) -> CefrLevel:
    """A word's level from its frequency rank: the first level whose cut it is within;
    past every cut (or no rank: a rare word) it is C2."""
    if rank is not None:
        for level, cut in rules.level_rank.items():
            if rank <= cut:
                return level
    return "C2"


def sentence_difficulty(ranks: Sequence[int | None], word_count: int, rules: Rules) -> float:
    """`ranks`: frequency ranks of the sentence's lexicon words (None = rare)."""
    levels = [level_of_rank(r, rules.pronunciation) for r in ranks]
    hardest: CefrLevel = max(levels, key=CEFR_LEVELS.index, default="A1")
    offset = next(
        (b.offset for b in rules.pronunciation.length_offsets if word_count <= b.max_words),
        rules.pronunciation.length_offsets[-1].offset,
    )
    return rules.difficulty.cefr_anchor[hardest] + offset


def counts_for_ability(assessment: Assessment, word_count: int, rules: Rules) -> bool:
    """Barely read, too few words or too short a recording says little about speaking."""
    p = rules.pronunciation
    return (
        assessment.scores.completeness >= p.min_completeness
        and word_count >= p.min_words
        and assessment.audio_seconds >= p.min_seconds
    )


async def shadow(
    session: AsyncSession,
    ctx: TenantProviderContext,
    *,
    user_id: uuid.UUID,
    audio: bytes,
    reference_text: str,
    language: Language,
    source: Source,
    source_id: str | None,
    rules: Rules,
    now: datetime,
) -> Outcome:
    """Score one reading and keep it; raises ShadowingError. Commits."""
    try:
        seconds = wav_seconds(audio)
    except InvalidAudioError as exc:
        raise ShadowingError("invalid_audio", str(exc)) from exc
    attempt = PronunciationAttempt(
        user_id=user_id,
        source=source,
        source_id=source_id,
        reference_text=reference_text,
        language=language,
        audio_seconds=seconds,
        created_at=now,
    )
    assessment: Assessment | None = None
    try:
        assessor = get_pronunciation(ctx)
    except NoModelConfiguredError:
        attempt.fallback_reason = "not_configured"
    else:
        try:
            assessment = await assessor.assess(
                audio, reference_text=reference_text, language=language, user_id=user_id
            )
        except NoSpeechError as exc:
            raise ShadowingError("no_speech", "nothing was heard in the recording") from exc
        except AssessmentError:
            attempt.fallback_reason = "failed"

    mispronounced: tuple[str, ...] = ()
    if assessment is not None:
        attempt.provider = "azure"
        attempt.scores = assessment.scores.model_dump()
        attempt.words = [w.model_dump(mode="json") for w in assessment.words]
        attempt.recognized_text = assessment.recognized_text
        mispronounced = await _record_evidence(
            session, user_id, attempt, assessment, rules=rules, now=now
        )
    else:
        await _compare_transcript(ctx, attempt, audio, user_id)
    session.add(attempt)
    await session.commit()
    return Outcome(attempt, mispronounced)


async def _compare_transcript(
    ctx: TenantProviderContext, attempt: PronunciationAttempt, audio: bytes, user_id: uuid.UUID
) -> None:
    try:
        stt = dataclasses.replace(get_asr(ctx), task=FALLBACK_TASK)
    except NoModelConfiguredError as exc:
        if attempt.fallback_reason == "failed":
            raise ShadowingError("unavailable", "pronunciation assessment failed") from exc
        raise ShadowingError("not_configured", "no pronunciation or speech-to-text model") from exc
    try:
        transcript = await stt.transcribe(
            audio, filename="shadowing.wav", mime_type="audio/wav", user_id=user_id
        )
    except TranscriptionError as exc:
        raise ShadowingError("unavailable", "speech-to-text failed") from exc
    if not heard_speech(transcript.text):
        raise ShadowingError("no_speech", "nothing was heard in the recording")
    result = compare(attempt.reference_text, transcript.text)
    attempt.provider = "asr_fallback"
    attempt.scores = None
    attempt.words = [w.model_dump(mode="json") for w in result.words]
    attempt.recognized_text = result.recognized_text


async def _record_evidence(
    session: AsyncSession,
    user_id: uuid.UUID,
    attempt: PronunciationAttempt,
    assessment: Assessment,
    *,
    rules: Rules,
    now: datetime,
) -> tuple[str, ...]:
    """Moves speaking ability (when the attempt counts) and records each lexicon word
    read; returns the words now below the threshold."""
    written = words_of(attempt.reference_text)
    entries = await glossary.load_entries(session, (w.lower() for w in written))

    if counts_for_ability(assessment, len(written), rules):
        difficulty = sentence_difficulty(
            [e.rank for w in written if (e := entries.get(w.lower())) is not None],
            len(written),
            rules,
        )
        ability = await _speaking_ability(session, user_id, rules)
        ability.rating = update_ability(
            ability.rating,
            difficulty,
            assessment.scores.overall / 100,
            ability.attempts,
            rules,
            0.0,
        )
        ability.attempts += 1
        attempt.counted = True

    # The lowest accuracy per lexicon word, for words actually read.
    read: dict[int, tuple[float, str]] = {}
    for w in assessment.words:
        entry = entries.get(w.word.lower())
        if entry is None or w.accuracy is None or w.error in ("omission", "insertion"):
            continue
        if entry.word_id not in read or w.accuracy < read[entry.word_id][0]:
            read[entry.word_id] = (w.accuracy, w.word.lower())
    if not read:
        return ()
    rows = {
        row.word_id: row
        for row in await session.scalars(
            select(WordPronunciation)
            .where(WordPronunciation.user_id == user_id, WordPronunciation.word_id.in_(read))
            .with_for_update()
        )
    }
    threshold = rules.pronunciation.word_threshold
    for word_id, (accuracy, _) in read.items():
        row = rows.get(word_id)
        if row is None:
            row = WordPronunciation(user_id=user_id, word_id=word_id, low_count=0)
            session.add(row)
        row.accuracy = accuracy
        row.assessed_at = now
        if accuracy < threshold:
            row.low_count += 1
            row.last_low_at = now
    return tuple(sorted({form for accuracy, form in read.values() if accuracy < threshold}))


async def _speaking_ability(
    session: AsyncSession, user_id: uuid.UUID, rules: Rules
) -> SkillEstimate:
    row = await session.scalar(
        select(SkillEstimate)
        .where(SkillEstimate.user_id == user_id, SkillEstimate.skill == SKILL)
        .with_for_update()
    )
    if row is None:
        # Like grammar: start from the anchor of the learner's level.
        level = cast(
            CefrLevel | None,
            await session.scalar(
                select(UserProfile.cefr_level).where(UserProfile.user_id == user_id)
            ),
        )
        anchor = rules.difficulty.cefr_anchor[level or rules.practice.default_level]
        row = SkillEstimate(user_id=user_id, skill=SKILL, rating=anchor, attempts=0)
        session.add(row)
    return row


async def mispronounced_words(
    session: AsyncSession, user_id: uuid.UUID, word_ids: Iterable[int], rules: Rules
) -> set[int]:
    """Of `word_ids`, the words the learner last read below the threshold (Q56c)."""
    wanted = list(set(word_ids))
    if not wanted:
        return set()
    rows = await session.scalars(
        select(WordPronunciation.word_id).where(
            WordPronunciation.user_id == user_id,
            WordPronunciation.word_id.in_(wanted),
            WordPronunciation.accuracy < rules.pronunciation.word_threshold,
        )
    )
    return set(rows)
