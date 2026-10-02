"""Which placement-test reminder to show (task 50, Q50a)."""

import uuid
from datetime import UTC, datetime, timedelta

from app.adaptive.rules import get_rules
from app.advice.reminder import LastTest, Reminder, ReminderSignals, decide

RULES = get_rules()
NOW = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)
TEST = uuid.UUID(int=1)
OPEN = uuid.UUID(int=2)


def last(days: float, learned: int = 0, total: int = 33) -> LastTest:
    return LastTest(TEST, NOW - timedelta(days=days), "B1", learned, total)


def at(signals: ReminderSignals) -> Reminder | None:
    return decide(signals, RULES, now=NOW)


def test_a_test_left_halfway_comes_first() -> None:
    assert at(ReminderSignals(OPEN, None)) == Reminder("resume", f"resume:{OPEN}")
    assert at(ReminderSignals(OPEN, last(90, 33))) == Reminder("resume", f"resume:{OPEN}")


def test_never_tested() -> None:
    assert at(ReminderSignals(None, None)) == Reminder("never", "never")


def test_nothing_while_recent_and_little_learned() -> None:
    assert at(ReminderSignals(None, last(10))) is None
    assert at(ReminderSignals(None, last(59, learned=22))) is None


def test_progress_needs_the_share_and_the_wait() -> None:
    share = RULES.advice.retest_learned_share
    enough = -(-33 * share // 1)  # the smallest count reaching the share
    wait = RULES.advice.retest_min_days
    assert at(ReminderSignals(None, last(wait - 0.5, learned=33))) is None
    assert at(ReminderSignals(None, last(wait, learned=int(enough) - 1))) is None
    assert at(ReminderSignals(None, last(wait, learned=int(enough)))) == Reminder(
        "progress", f"progress:{TEST}", wait, "B1", int(enough), 33
    )


def test_progress_beats_age() -> None:
    found = at(ReminderSignals(None, last(RULES.advice.retest_days, learned=30)))
    assert found is not None and found.reason == "progress"


def test_age() -> None:
    days = RULES.advice.retest_days
    assert at(ReminderSignals(None, last(days, learned=1))) == Reminder(
        "age", f"age:{TEST}", days, "B1", 1, 33
    )


def test_a_level_without_grammar_points_never_counts_as_progress() -> None:
    assert at(ReminderSignals(None, last(20, learned=0, total=0))) is None
