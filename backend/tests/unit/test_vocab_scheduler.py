"""FSRS state <-> user_cards columns, and the learner's day (ADR 0011)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import fsrs

from app.adaptive.rules import get_rules
from app.db.models import UserCard
from app.services.vocab.books import BOOKS, get_book
from app.services.vocab.scheduler import (
    day_bounds,
    preview,
    retrievability,
    scheduler,
    to_fsrs,
    zone,
)

RULES = get_rules()
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def test_state_survives_the_round_trip_through_columns() -> None:
    card = UserCard(id=7, status="new")
    assert to_fsrs(card).state == fsrs.State.Learning and to_fsrs(card).stability is None
    assert retrievability(card, RULES, NOW) is None

    scheduled, _ = scheduler(RULES).review_card(to_fsrs(card), fsrs.Rating.Good, NOW)
    for _ in range(2):  # through the learning steps into review
        scheduled, _ = scheduler(RULES).review_card(scheduled, fsrs.Rating.Good, scheduled.due)
    stored = UserCard(
        id=7,
        status="learning",
        state=scheduled.state.value,
        step=scheduled.step,
        stability=scheduled.stability,
        difficulty=scheduled.difficulty,
        due=scheduled.due,
        last_review=scheduled.last_review,
    )
    assert to_fsrs(stored).to_dict() == scheduled.to_dict()
    assert scheduled.state == fsrs.State.Review
    assert scheduled.last_review is not None
    fresh = retrievability(stored, RULES, scheduled.last_review)
    later = retrievability(stored, RULES, scheduled.last_review + timedelta(days=30))
    assert fresh is not None and later is not None and 0 < later < fresh <= 1


def test_the_day_follows_the_learners_clock() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    # 01:30 in Shanghai is still the previous day in UTC.
    start, end = day_bounds(datetime(2026, 9, 29, 17, 30, tzinfo=UTC), shanghai)
    assert start == datetime(2026, 9, 29, 16, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=24)
    # The day DST ends in New York has 25 hours.
    start, end = day_bounds(datetime(2026, 11, 1, 15, 0, tzinfo=UTC), ZoneInfo("America/New_York"))
    assert start == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=25)


def test_unknown_zones_are_ignored() -> None:
    assert zone("Europe/Paris") == ZoneInfo("Europe/Paris")
    assert zone("Mars/Olympus") is None and zone("") is None and zone(None) is None
    assert zone("../etc/passwd") is None


def test_books() -> None:
    assert len(BOOKS) == 9 and len({b.id for b in BOOKS}) == 9
    assert get_book("cet4") is not None and get_book("nope") is None


def test_preview_gives_each_rating_its_interval_without_changing_the_card() -> None:
    # A word never met: the learning steps (1 and 10 minutes), Easy skips them by days.
    again, hard, good, easy = preview(None, RULES, NOW)
    assert (again, good) == (60, 600)
    assert again < hard < good < easy and easy >= 86_400

    card = UserCard(id=7, status="new")
    assert preview(card, RULES, NOW) == [again, hard, good, easy]
    assert card.state is None  # previewing reviews a copy

    # A card in review: what Good actually schedules, minus the fuzz.
    scheduled, _ = scheduler(RULES).review_card(to_fsrs(card), fsrs.Rating.Easy, NOW)
    stored = UserCard(
        id=7,
        status="learning",
        state=scheduled.state.value,
        step=scheduled.step,
        stability=scheduled.stability,
        difficulty=scheduled.difficulty,
        due=scheduled.due,
        last_review=scheduled.last_review,
    )
    intervals = preview(stored, RULES, scheduled.due)
    assert intervals == sorted(intervals) and intervals[0] < 86_400 < intervals[2]
