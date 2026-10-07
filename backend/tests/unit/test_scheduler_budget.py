"""The daily background budget's arithmetic (ADR 0025 §5)."""

from datetime import UTC, datetime, timedelta, timezone

from app.scheduler.budget import Budget, day_start


def test_exhausted_at_the_limit() -> None:
    assert not Budget(limit=100_000, used=99_999).exhausted
    assert Budget(limit=100_000, used=100_000).exhausted
    assert Budget(limit=100_000, used=150_000).exhausted


def test_zero_turns_background_work_off() -> None:
    assert Budget(limit=0, used=0).exhausted


def test_the_day_starts_at_midnight_utc() -> None:
    assert day_start(datetime(2026, 10, 7, 23, 59, tzinfo=UTC)) == datetime(2026, 10, 7, tzinfo=UTC)
    # 07:30 in Beijing on the 8th is still the 7th in UTC.
    beijing = timezone(timedelta(hours=8))
    assert day_start(datetime(2026, 10, 8, 7, 30, tzinfo=beijing)) == datetime(
        2026, 10, 7, tzinfo=UTC
    )
