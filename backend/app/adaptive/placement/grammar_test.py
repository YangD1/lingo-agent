"""Adaptive grammar test over the placement item bank (ADR 0010 §4, P1 plan §6.1).

Pure functions: the placement graph (task 15) keeps the answers and calls these.

Ability is on the same logit scale as item difficulty, with the Elo model's chance of
a correct answer (`elo.expected`, guessing floor for four options). It is the maximum
a posteriori fit over all answers so far under a normal prior, not a running Elo
update: with at most 20 answers a running update depends on their order, while the
fit does not, and it comes with a standard error for the stopping rule. Item
difficulties are not touched during the test (ADR 0012 §3); they are re-estimated
afterwards from the final ability.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from app.adaptive.elo import expected, guess_for
from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel
from app.adaptive.placement.items import Item, ItemBank
from app.adaptive.rules import Rules

# Ability is searched over this range: a coarse grid, then a fine one around the best.
_MIN, _MAX, _GRID = -6.0, 6.0, 60


@dataclass(frozen=True, slots=True)
class GrammarAnswer:
    item_id: str
    correct: bool


@dataclass(frozen=True, slots=True)
class GrammarResult:
    ability: float
    standard_error: float
    cefr: CefrLevel
    answered: int


def _answered(answers: Sequence[GrammarAnswer], bank: ItemBank) -> list[tuple[Item, bool]]:
    pairs = []
    for a in answers:
        item = bank.get(a.item_id)
        if item is None:
            raise ValueError(f"unknown item {a.item_id}")
        pairs.append((item, a.correct))
    return pairs


def _log_posterior(
    ability: float, pairs: Sequence[tuple[Item, bool]], guess: float, rules: Rules
) -> float:
    prior_sd = rules.placement.grammar.prior_sd
    total = -((ability - rules.elo.initial_ability) ** 2) / (2 * prior_sd**2)
    for item, correct in pairs:
        p = expected(ability, item.difficulty, guess)
        total += math.log(p if correct else 1 - p)
    return total


def fit_ability(answers: Sequence[GrammarAnswer], bank: ItemBank, rules: Rules) -> float:
    """The most probable ability given the answers (the prior mean when there are none)."""
    pairs = _answered(answers, bank)
    guess = guess_for(bank.format, rules)
    low, high = _MIN, _MAX
    for _ in range(2):
        step = (high - low) / _GRID
        best = max(
            (low + i * step for i in range(_GRID + 1)),
            key=lambda a: _log_posterior(a, pairs, guess, rules),
        )
        low, high = max(_MIN, best - step), min(_MAX, best + step)
    return best


def standard_error(
    ability: float, answers: Sequence[GrammarAnswer], bank: ItemBank, rules: Rules
) -> float:
    """Posterior standard error of the ability: prior plus each item's Fisher information."""
    guess = guess_for(bank.format, rules)
    information = 1 / rules.placement.grammar.prior_sd**2
    for item, _ in _answered(answers, bank):
        p = expected(ability, item.difficulty, guess)
        logistic = (p - guess) / (1 - guess)
        slope = (1 - guess) * logistic * (1 - logistic)
        information += slope**2 / (p * (1 - p))
    return 1 / math.sqrt(information)


def pick_item(
    answers: Sequence[GrammarAnswer], bank: ItemBank, rules: Rules, rng: random.Random
) -> Item | None:
    """The next item, or None when every item has been answered.

    Candidates are the unanswered items on KCs not yet tested (all unanswered items once
    every KC has been); among those whose predicted chance of a correct answer is within
    `pick_tolerance` of the closest to `target_p`, one is drawn at random.
    """
    r = rules.placement.grammar
    done = {a.item_id for a in answers}
    tested_kcs = {item.kc for item, _ in _answered(answers, bank)}
    unanswered = [i for i in bank.items if i.id not in done]
    if not unanswered:
        return None
    candidates = [i for i in unanswered if i.kc not in tested_kcs] or unanswered
    ability = fit_ability(answers, bank, rules)
    guess = guess_for(bank.format, rules)

    def distance(item: Item) -> float:
        return abs(expected(ability, item.difficulty, guess) - r.target_p)

    best = min(distance(i) for i in candidates)
    near = sorted(
        (i for i in candidates if distance(i) <= best + r.pick_tolerance), key=lambda i: i.id
    )
    return rng.choice(near)


def finished(answers: Sequence[GrammarAnswer], bank: ItemBank, rules: Rules) -> bool:
    r = rules.placement.grammar
    n = len(answers)
    if n >= r.max_items or n >= len(bank.items):
        return True
    if n < r.min_items:
        return False
    ability = fit_ability(answers, bank, rules)
    return standard_error(ability, answers, bank, rules) < r.stop_se


def cefr_for(ability: float, rules: Rules) -> CefrLevel:
    cuts = rules.placement.grammar.cefr_cutpoints
    level: CefrLevel = CEFR_LEVELS[0]
    for candidate in CEFR_LEVELS[1:]:
        if ability >= cuts[candidate]:
            level = candidate
    return level


def result(answers: Sequence[GrammarAnswer], bank: ItemBank, rules: Rules) -> GrammarResult:
    ability = fit_ability(answers, bank, rules)
    return GrammarResult(
        ability=ability,
        standard_error=standard_error(ability, answers, bank, rules),
        cefr=cefr_for(ability, rules),
        answered=len(answers),
    )
