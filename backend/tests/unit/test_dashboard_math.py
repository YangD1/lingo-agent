"""The dashboard's pure pieces: the shared CEFR scale (Q17d) and the streak (Q17c)."""

from datetime import date, timedelta

import pytest

from app.adaptive import cefr_scale
from app.adaptive.rules import get_rules
from app.dashboard.service import streak

CUTS = {"A2": -1.8, "B1": -0.8, "B2": 0.4, "C1": 1.2, "C2": 2.4}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-1.8, 1.0),  # the A2 cut is where A2 starts
        (-1.3, 1.5),  # halfway through A2
        (0.4, 3.0),
        (0.8, 3.5),
        (-2.8, 0.0),  # A1 borrows A2's width: one width below the A2 cut is 0
        (-2.3, 0.5),
        (-10.0, 0.0),  # clamped
        (3.0, 5.5),  # C2 borrows C1's width (1.2)
        (10.0, 6.0),
    ],
)
def test_position_places_values_between_their_levels_cuts(value: float, expected: float) -> None:
    assert cefr_scale.position(value, CUTS) == pytest.approx(expected)


def test_position_agrees_with_the_level_of_each_skill() -> None:
    rules = get_rules()
    grammar = rules.placement.grammar.cefr_cutpoints
    vocab = rules.placement.vocab.cefr_reference
    assert vocab is not None
    # Every level's own range: position floor is its index.
    assert int(cefr_scale.position(grammar["B1"] + 0.01, grammar)) == 2
    assert int(cefr_scale.position(vocab.thresholds["B2"] + 1, vocab.thresholds)) == 3
    assert cefr_scale.position(vocab.basis, vocab.thresholds) <= cefr_scale.TOP


TODAY = date(2026, 9, 30)


def days_ago(*offsets: int) -> list[date]:
    return [TODAY - timedelta(days=n) for n in offsets]


@pytest.mark.parametrize(
    ("studied", "expected"),
    [
        ([], 0),
        (days_ago(0), 1),
        (days_ago(0, 1, 2), 3),
        # Not studied yet today: the run up to yesterday still counts.
        (days_ago(1, 2), 2),
        # A missed day breaks it.
        (days_ago(0, 2, 3), 1),
        (days_ago(2, 3), 0),
    ],
)
def test_streak_counts_back_from_today_or_yesterday(studied: list[date], expected: int) -> None:
    assert streak(studied, TODAY) == expected
