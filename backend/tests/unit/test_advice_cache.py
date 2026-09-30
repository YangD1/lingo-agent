"""When cached advice is regenerated (Q18b)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.advice.candidates import Candidate
from app.advice.service import (
    MIN_INTERVAL,
    STALE_AFTER,
    advice_locale,
    by_hand_after,
    needs_refresh,
    stored_items,
)
from app.advice.writer import Item
from app.db.models import LearningAdvice

NOW = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)
FOUND = [Candidate("vocab_review", "vocab_review", 0.5), Candidate("placement", "placement", 1)]


def row(age: timedelta, *, ids: list[str] | None = None, locale: str = "en") -> LearningAdvice:
    return LearningAdvice(
        items=[{"candidate_id": "vocab_review", "title": "Review", "reason": "Why"}],
        candidate_ids=["placement", "vocab_review"] if ids is None else ids,
        locale=locale,
        status="ai",
        generated_at=NOW - age,
    )


def test_no_advice_yet_is_generated() -> None:
    assert needs_refresh(None, FOUND, "en", NOW)


def test_same_candidates_in_any_order_keep_the_advice_until_it_is_old() -> None:
    assert not needs_refresh(row(STALE_AFTER - timedelta(minutes=1)), FOUND, "en", NOW)
    assert needs_refresh(row(STALE_AFTER), FOUND, "en", NOW)


@pytest.mark.parametrize(
    "changed", [{"ids": ["placement"]}, {"ids": ["placement", "vocab_review", "choose_book"]}]
)
def test_other_candidates_regenerate_but_not_too_often(changed: dict[str, list[str]]) -> None:
    assert not needs_refresh(row(MIN_INTERVAL - timedelta(seconds=1), **changed), FOUND, "en", NOW)
    assert needs_refresh(row(MIN_INTERVAL, **changed), FOUND, "en", NOW)


def test_a_placement_test_after_the_advice_regenerates_it_at_once() -> None:
    fresh = row(timedelta(minutes=1), ids=["vocab_review"])  # the placement one is gone
    assert not needs_refresh(fresh, FOUND, "en", NOW)
    assert needs_refresh(fresh, FOUND, "en", NOW, placed_at=NOW - timedelta(seconds=5))
    # Once rewritten after the test, the interval applies again.
    assert not needs_refresh(fresh, FOUND, "en", NOW, placed_at=NOW - timedelta(minutes=2))


def test_another_language_regenerates_and_hides_the_models_text() -> None:
    zh = row(MIN_INTERVAL, locale="zh-CN")
    assert needs_refresh(zh, FOUND, "en", NOW)
    assert stored_items(zh, "en") == []
    assert stored_items(zh, "zh-CN") == [Item("vocab_review", "Review", "Why")]


def test_refresh_by_hand_once_an_hour() -> None:
    advice = row(timedelta(0))
    assert by_hand_after(advice, NOW) is None
    advice.refreshed_by_hand_at = NOW - timedelta(minutes=20)
    assert by_hand_after(advice, NOW) == NOW + timedelta(minutes=40)
    advice.refreshed_by_hand_at = NOW - timedelta(hours=1)
    assert by_hand_after(advice, NOW) is None


@pytest.mark.parametrize(
    ("raw", "locale"),
    [("zh-CN", "zh-CN"), ("zh", "zh-CN"), ("en", "en"), ("fr", "en"), (None, "en")],
)
def test_locale(raw: str | None, locale: str) -> None:
    assert advice_locale(raw) == locale
