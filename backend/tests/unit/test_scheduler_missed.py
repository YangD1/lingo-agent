"""When a scheduled job counts as having missed a period (ADR 0025 §3)."""

from datetime import UTC, datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.scheduler.service import describe_error, missed

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_never_finished_counts_as_missed() -> None:
    assert missed(IntervalTrigger(hours=2, timezone=UTC), None, NOW)


def test_interval_within_period_is_not_missed() -> None:
    trigger = IntervalTrigger(hours=2, timezone=UTC)
    assert not missed(trigger, NOW - timedelta(minutes=90), NOW)


def test_interval_past_period_is_missed() -> None:
    trigger = IntervalTrigger(hours=2, timezone=UTC)
    assert missed(trigger, NOW - timedelta(hours=2, minutes=1), NOW)
    # Many missed periods are still one catch-up: the answer is just yes.
    assert missed(trigger, NOW - timedelta(days=3), NOW)


def test_weekly_cron() -> None:
    weekly = CronTrigger(day_of_week="mon", hour=3, timezone=UTC)  # NOW is a Wednesday
    assert not missed(weekly, datetime(2026, 10, 5, 3, 5, tzinfo=UTC), NOW)
    assert missed(weekly, datetime(2026, 10, 4, 3, 5, tzinfo=UTC), NOW)


def test_error_text_is_cut_short() -> None:
    text = describe_error(ValueError("x" * 1000))
    assert text.startswith("ValueError: x")
    assert len(text) == 500
