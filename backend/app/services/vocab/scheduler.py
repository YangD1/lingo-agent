"""Reviewing a word with FSRS (py-fsrs, default parameters; ADR 0011).

`user_cards` keeps the fields of `fsrs.Card` as columns; this module converts between
the two, records each review in `review_logs`, and says where a learner's day starts.
Times are UTC throughout; only the day boundary uses the learner's time zone.
"""

import uuid
from datetime import UTC, datetime, time, timedelta
from functools import cache
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import fsrs
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.rules import Rules
from app.db.models import ReviewLog, UserCard, UserProfile, Word

type Rating = Literal[1, 2, 3, 4]  # again, hard, good, easy
type CardSource = Literal["book", "auto", "manual"]


class WordNotFoundError(Exception):
    pass


@cache
def _scheduler(desired_retention: float) -> fsrs.Scheduler:
    return fsrs.Scheduler(desired_retention=desired_retention)


def scheduler(rules: Rules) -> fsrs.Scheduler:
    return _scheduler(rules.vocab.desired_retention)


@cache
def _preview_scheduler(desired_retention: float) -> fsrs.Scheduler:
    # Without fuzzing: the interval itself, not one random draw around it.
    return fsrs.Scheduler(desired_retention=desired_retention, enable_fuzzing=False)


RATINGS: tuple[Rating, ...] = (1, 2, 3, 4)


def preview(card: UserCard | None, rules: Rules, now: datetime | None = None) -> list[int]:
    """Seconds until the next review for ratings 1-4, were the word rated now (task 27.5).

    Shown on the rating buttons; `review` adds fuzzing, so a long interval can land a
    few days either side.
    """
    now = now or datetime.now(UTC)
    # card_id given: py-fsrs sleeps 1ms to make up an id otherwise.
    current = to_fsrs(card) if card else fsrs.Card(card_id=0, due=now)
    sched = _preview_scheduler(rules.vocab.desired_retention)
    dues = [sched.review_card(current, fsrs.Rating(r), now)[0].due for r in RATINGS]
    return [max(0, round((due - now).total_seconds())) for due in dues]


def to_fsrs(card: UserCard) -> fsrs.Card:
    """The card as py-fsrs sees it; a never-reviewed card is a fresh fsrs.Card."""
    if card.state is None:
        return fsrs.Card(card_id=card.id)
    return fsrs.Card(
        card_id=card.id,
        state=fsrs.State(card.state),
        step=card.step,
        stability=card.stability,
        difficulty=card.difficulty,
        due=card.due,
        last_review=card.last_review,
    )


def _apply(card: UserCard, scheduled: fsrs.Card) -> None:
    card.state = scheduled.state.value
    card.step = scheduled.step
    card.stability = scheduled.stability
    card.difficulty = scheduled.difficulty
    card.due = scheduled.due
    card.last_review = scheduled.last_review


def _snapshot(card: UserCard) -> dict[str, Any]:
    if card.state is None:
        return {"status": card.status}
    state: dict[str, Any] = dict(to_fsrs(card).to_dict())
    del state["card_id"]
    return {"status": card.status, **state}


async def review(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    word_id: int,
    rating: Rating,
    rules: Rules,
    now: datetime | None = None,
    duration_ms: int | None = None,
    source: CardSource = "book",
) -> UserCard:
    """Rate the learner's recall of a word and schedule its next review; does not commit.

    A word without a card (a book word shown for the first time) gets one here, with
    `source`. Reviewing a known or suspended word puts it back into learning.
    """
    now = now or datetime.now(UTC)
    if await session.get(Word, word_id) is None:
        raise WordNotFoundError(word_id)
    # Concurrent first reviews of one word must not create two cards.
    await session.execute(
        insert(UserCard)
        .values(user_id=user_id, word_id=word_id, source=source, status="new")
        .on_conflict_do_nothing(index_elements=["user_id", "word_id"])
    )
    card = await session.scalar(
        select(UserCard)
        .where(UserCard.user_id == user_id, UserCard.word_id == word_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert card is not None
    before = _snapshot(card)
    scheduled, _ = scheduler(rules).review_card(to_fsrs(card), fsrs.Rating(rating), now)
    _apply(card, scheduled)
    card.status = "learning"
    card.first_reviewed_at = card.first_reviewed_at or now
    session.add(
        ReviewLog(
            card_id=card.id,
            user_id=user_id,
            rating=rating,
            reviewed_at=now,
            review_duration_ms=duration_ms,
            card_before=before,
            card_after=_snapshot(card),
        )
    )
    await session.flush()
    return card


def retrievability(card: UserCard, rules: Rules, now: datetime | None = None) -> float | None:
    """Chance the learner recalls the word now; None if it was never reviewed.

    The word's mastery (ADR 0010): computed when needed, never stored, because it
    falls as time passes.
    """
    if card.state is None:
        return None
    return scheduler(rules).get_card_retrievability(to_fsrs(card), now or datetime.now(UTC))


def zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


async def learner_zone(
    session: AsyncSession, user_id: uuid.UUID, fallback: str | None = None
) -> ZoneInfo:
    """The profile's time zone, else `fallback` (the browser's), else UTC."""
    stored = await session.scalar(
        select(UserProfile.timezone).where(UserProfile.user_id == user_id)
    )
    return zone(stored) or zone(fallback) or ZoneInfo("UTC")


def day_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Start and end, in UTC, of the learner's calendar day containing `now`."""
    today = now.astimezone(tz).date()
    start = datetime.combine(today, time(), tzinfo=tz)
    end = datetime.combine(today + timedelta(days=1), time(), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)
