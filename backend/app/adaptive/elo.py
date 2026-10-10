"""Elo ratings for learner ability and item difficulty (ADR 0010 §2, ADR 0012 §3).

Ratings are on a logit scale. The step size shrinks with the number of answers,
K(n) = alpha / (1 + beta * n) (Pelanek 2016), so new learners and new items move fast
and settle as evidence accumulates; K(n) doubles as the estimate's uncertainty.
"""

import math
from collections.abc import Mapping

from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import EloK, Rules


def expected(ability: float, difficulty: float, guess: float = 0.0) -> float:
    """Chance of a correct answer; `guess` is the floor from blind guessing."""
    x = ability - difficulty
    # Written this way so large |x| cannot overflow math.exp.
    logistic = 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))
    return guess + (1 - guess) * logistic


def k_factor(n: int, k: EloK) -> float:
    """Step size after `n` answers; also the uncertainty of the rating."""
    return k.alpha / (1 + k.beta * n)


def guess_for(item_format: str, rules: Rules) -> float:
    return rules.elo.guess_by_format.get(item_format, 0.0)


def update_ability(
    ability: float,
    difficulty: float,
    correct: bool | float,
    answers: int,
    rules: Rules,
    guess: float,
) -> float:
    """New learner ability after one answer; `answers` counts the learner's earlier ones.

    `correct` may also be a graded outcome in [0, 1], such as a pronunciation score / 100
    (ADR 0028 §6)."""
    surprise = float(correct) - expected(ability, difficulty, guess)
    return ability + k_factor(answers, rules.elo.learner) * surprise


def update_item(
    difficulty: float, ability: float, correct: bool, answers: int, rules: Rules, guess: float
) -> float:
    """New item difficulty after one answer; `answers` counts the item's earlier ones.

    Pass a settled ability (e.g. the learner's final placement estimate), not one that
    is still moving, or the item absorbs the learner's estimation error.
    """
    surprise = float(correct) - expected(ability, difficulty, guess)
    return difficulty - k_factor(answers, rules.elo.item) * surprise


def prior_difficulty(target: CefrLevel, ratings: Mapping[str, str], rules: Rules) -> float:
    """Difficulty before anyone has answered, from a per-dimension rubric rating.

    `ratings` maps every rubric dimension to one of its level names, as chosen by the
    model that reviews the item. Raises ValueError on a missing, extra or unknown one.
    """
    dimensions = rules.difficulty.dimensions
    if (given := set(ratings)) != (wanted := set(dimensions)):
        raise ValueError(
            f"rubric dimensions differ: missing {sorted(wanted - given)}, "
            f"unexpected {sorted(given - wanted)}"
        )
    total = rules.difficulty.cefr_anchor[target]
    for name, level in ratings.items():
        levels = dimensions[name].levels
        if level not in levels:
            raise ValueError(f"{name}: unknown level {level!r}, expected one of {sorted(levels)}")
        total += levels[level].offset
    return total
