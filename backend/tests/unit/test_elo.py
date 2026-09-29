import math

import pytest

from app.adaptive.elo import (
    expected,
    guess_for,
    k_factor,
    prior_difficulty,
    update_ability,
    update_item,
)
from app.adaptive.rules import EloK, EloRules, Rules, load_rules


@pytest.fixture
def rules() -> Rules:
    """Fixed Elo parameters, so these tests don't move when rules.yaml is tuned."""
    base = load_rules()
    elo = EloRules(
        learner=EloK(alpha=1.0, beta=0.05),
        item=EloK(alpha=0.8, beta=0.05),
        initial_ability=0.0,
        guess_by_format={"choice4": 0.25},
    )
    return base.model_copy(update={"elo": elo})


def test_expected() -> None:
    assert expected(0.0, 0.0) == 0.5
    assert expected(1.0, 0.0) == pytest.approx(1 / (1 + math.exp(-1)))
    assert expected(0.0, 0.0, guess=0.25) == pytest.approx(0.625)
    # Far below an item's difficulty, a four-option item still gives the guessing floor.
    assert expected(-50.0, 50.0, guess=0.25) == pytest.approx(0.25)
    assert expected(1000.0, 0.0) == pytest.approx(1.0)  # no overflow


def test_k_decays_with_answers(rules: Rules) -> None:
    ks = [k_factor(n, rules.elo.learner) for n in (0, 1, 10, 100)]
    assert ks[0] == 1.0
    assert ks == sorted(ks, reverse=True)
    assert ks[2] == pytest.approx(1 / 1.5)


def test_ability_moves_in_the_right_direction(rules: Rules) -> None:
    assert update_ability(0.0, 0.0, True, 0, rules, 0.25) > 0.0
    assert update_ability(0.0, 0.0, False, 0, rules, 0.25) < 0.0
    # Same surprise, later answer: smaller step.
    assert abs(update_ability(0.0, 0.0, True, 50, rules, 0.0)) < abs(
        update_ability(0.0, 0.0, True, 0, rules, 0.0)
    )


def test_strong_learner_gains_little_from_an_easy_item(rules: Rules) -> None:
    assert update_ability(3.0, -2.0, True, 0, rules, 0.25) - 3.0 < 0.01
    # ...and a weak learner's lucky guess on a hard item moves less with a guess floor.
    lucky_mc = update_ability(-2.0, 2.0, True, 0, rules, 0.25) + 2.0
    lucky_open = update_ability(-2.0, 2.0, True, 0, rules, 0.0) + 2.0
    assert 0 < lucky_mc < lucky_open


def test_item_moves_opposite_to_the_learner(rules: Rules) -> None:
    assert update_item(0.0, 0.0, True, 0, rules, 0.25) < 0.0  # answered: easier
    assert update_item(0.0, 0.0, False, 0, rules, 0.25) > 0.0  # missed: harder
    assert update_item(0.0, 0.0, False, 0, rules, 0.0) == pytest.approx(0.8 * 0.5)


def test_guess_for_unknown_format_is_zero(rules: Rules) -> None:
    assert guess_for("choice4", rules) == 0.25
    assert guess_for("open", rules) == 0.0


def test_prior_difficulty_sums_anchor_and_offsets() -> None:
    rules = load_rules()
    ratings = {name: next(iter(dim.levels)) for name, dim in rules.difficulty.dimensions.items()}
    want = rules.difficulty.cefr_anchor["B1"] + sum(
        rules.difficulty.dimensions[n].levels[lv].offset for n, lv in ratings.items()
    )
    assert prior_difficulty("B1", ratings, rules) == pytest.approx(want)
    assert prior_difficulty("C1", ratings, rules) > prior_difficulty("B1", ratings, rules)


def test_prior_difficulty_rejects_bad_ratings() -> None:
    rules = load_rules()
    ratings = {name: next(iter(dim.levels)) for name, dim in rules.difficulty.dimensions.items()}
    first = next(iter(ratings))
    with pytest.raises(ValueError, match="missing"):
        prior_difficulty("B1", {k: v for k, v in ratings.items() if k != first}, rules)
    with pytest.raises(ValueError, match="unexpected"):
        prior_difficulty("B1", ratings | {"mood": "sunny"}, rules)
    with pytest.raises(ValueError, match="unknown level"):
        prior_difficulty("B1", ratings | {first: "impossible"}, rules)
