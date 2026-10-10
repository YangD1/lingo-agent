"""Drafting and checking a day's plan (ADR 0027 §2-§3)."""

import dataclasses

from app.adaptive.daily_plan.algorithm import (
    ITEM_KINDS,
    PlanChoice,
    PlanInputs,
    clamp,
    draft,
    items,
    total_minutes,
)
from app.adaptive.rules import get_rules

RULES = get_rules()
R = RULES.daily_plan

# 20 minutes, a little of everything.
BASE = PlanInputs(
    minutes=20,
    reviews_due=12,
    new_left=10,
    practice_kc="g.present_simple",
    article_id=7,
    days_since_writing=None,
)


def with_(**changes: object) -> PlanInputs:
    return dataclasses.replace(BASE, **changes)  # type: ignore[arg-type]


def test_rules_numbers_the_tests_assume() -> None:
    assert R.default_minutes == 20
    assert R.review_share == 0.6
    assert (R.minutes.review, R.minutes.new_word, R.minutes.practice) == (0.25, 1.0, 8)
    assert (R.minutes.reading, R.minutes.writing) == (10, 15)
    assert (R.writing_min_minutes, R.writing_gap_days) == (45, 7)


def test_fills_in_order_reviews_practice_new_words() -> None:
    # 12 reviews = 3 min, practice 8, 9 left -> 9 new words, nothing for reading.
    assert draft(BASE, RULES) == PlanChoice(review=12, new_words=9, practice=True)


def test_review_backlog_capped_at_share_then_topped_up() -> None:
    # 400 due: 60% of 20 min = 48 reviews (12 min), practice 8, nothing left.
    assert draft(with_(reviews_due=400), RULES) == PlanChoice(review=48, practice=True)
    # Without practice or new words the leftover goes back to the backlog.
    alone = with_(reviews_due=400, practice_kc=None, new_left=0, article_id=None)
    assert draft(alone, RULES) == PlanChoice(review=80)


def test_no_minutes_uses_default() -> None:
    assert draft(with_(minutes=None), RULES) == draft(BASE, RULES)


def test_too_little_time_for_practice_goes_to_new_words() -> None:
    plan = draft(with_(minutes=10), RULES)
    # 12 reviews = 3 min, 7 left < 8: no practice, 7 new words.
    assert plan == PlanChoice(review=12, new_words=7)


def test_new_words_capped_by_book_then_reading() -> None:
    plan = draft(with_(minutes=30, new_left=5), RULES)
    # 3 + 8 + 5 = 16, 14 left: reading 10, 4 left -> no essay (under 45 min anyway).
    assert plan == PlanChoice(review=12, new_words=5, practice=True, reading=True)


def test_nothing_to_practise_or_read() -> None:
    plan = draft(with_(minutes=60, practice_kc=None, article_id=None, new_left=0), RULES)
    assert not plan.practice and not plan.reading
    # 12 reviews + essay (60 >= 45, never wrote).
    assert plan == PlanChoice(review=12, writing=True)


def test_writing_needs_enough_minutes_and_a_gap() -> None:
    long_day = with_(minutes=60, new_left=0)
    assert draft(long_day, RULES).writing
    assert not draft(dataclasses.replace(long_day, minutes=40), RULES).writing
    assert not draft(dataclasses.replace(long_day, days_since_writing=3), RULES).writing
    assert draft(dataclasses.replace(long_day, days_since_writing=7), RULES).writing


def test_empty_day() -> None:
    empty = PlanInputs(20, 0, 0, None, None, 3)
    assert draft(empty, RULES) == PlanChoice()
    assert items(PlanChoice(), empty, RULES) == ()


def test_clamp_keeps_within_today() -> None:
    asked = PlanChoice(review=999, new_words=999, practice=True, reading=True, writing=True)
    assert clamp(asked, BASE, RULES) == PlanChoice(12, 10, True, True, True)
    none = with_(practice_kc=None, article_id=None)
    assert clamp(asked, none, RULES) == PlanChoice(12, 10, False, False, True)
    assert clamp(PlanChoice(review=-3, new_words=-1), BASE, RULES) == PlanChoice()


def test_clamp_respects_max_count() -> None:
    many = with_(reviews_due=10_000)
    assert clamp(PlanChoice(review=10_000), many, RULES).review == R.max_count


def test_items_in_order_with_minutes_and_refs() -> None:
    choice = PlanChoice(
        review=20, new_words=5, practice=True, reading=True, writing=True, speaking=True
    )
    plan = items(choice, BASE, RULES)
    assert tuple(i.kind for i in plan) == ITEM_KINDS
    by_kind = {i.kind: i for i in plan}
    assert by_kind["review"].count == 20 and by_kind["review"].minutes == 5
    assert by_kind["new_words"].count == 5 and by_kind["new_words"].minutes == 5
    assert by_kind["practice"].ref == "g.present_simple"
    assert by_kind["reading"].ref == 7
    assert by_kind["writing"].count is None
    # Speaking counts minutes the learner speaks (Q59d).
    assert by_kind["speaking"].count == 5 and by_kind["speaking"].minutes == 10
    assert total_minutes(plan) == 5 + 5 + 8 + 10 + 15 + 10


def test_speaking_is_never_drafted_but_kept() -> None:
    for minutes in (20, 120, 600):
        assert not draft(with_(minutes=minutes), RULES).speaking
    assert clamp(PlanChoice(speaking=True), BASE, RULES).speaking


def test_draft_fits_budget() -> None:
    for minutes in (5, 10, 20, 30, 45, 60, 120):
        for due in (0, 7, 50, 400):
            inputs = with_(minutes=minutes, reviews_due=due, days_since_writing=None)
            plan = items(draft(inputs, RULES), inputs, RULES)
            assert total_minutes(plan) <= minutes + 1e-6
