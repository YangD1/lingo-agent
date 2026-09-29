import random
import statistics

import pytest

from app.adaptive.elo import expected
from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel
from app.adaptive.placement.grammar_test import (
    GrammarAnswer,
    cefr_for,
    finished,
    fit_ability,
    pick_item,
    result,
    standard_error,
)
from app.adaptive.placement.items import ItemBank, get_item_bank
from app.adaptive.rules import PlacementGrammarRules, Rules, load_rules

# The middle of each level's ability range under the cutpoints below.
TRUE_ABILITY: dict[CefrLevel, float] = {
    "A1": -2.6, "A2": -1.3, "B1": -0.2, "B2": 0.8, "C1": 1.8, "C2": 3.0,
}  # fmt: skip


@pytest.fixture
def rules() -> Rules:
    """Fixed test parameters, so these tests don't move when rules.yaml is tuned."""
    base = load_rules()
    grammar = PlacementGrammarRules(
        target_p=0.55,
        pick_tolerance=0.05,
        min_items=8,
        max_items=20,
        stop_se=0.55,
        prior_sd=1.5,
        cefr_cutpoints={"A2": -1.8, "B1": -0.8, "B2": 0.4, "C1": 1.2, "C2": 2.4},
    )
    placement = base.placement.model_copy(update={"grammar": grammar})
    return base.model_copy(update={"placement": placement})


@pytest.fixture
def bank() -> ItemBank:
    return get_item_bank()


def run(true_ability: float, bank: ItemBank, rules: Rules, seed: int) -> list[GrammarAnswer]:
    rng = random.Random(seed)
    answers: list[GrammarAnswer] = []
    while not finished(answers, bank, rules):
        item = pick_item(answers, bank, rules, rng)
        assert item is not None
        p = expected(true_ability, item.difficulty, 0.25)
        answers.append(GrammarAnswer(item.id, rng.random() < p))
    return answers


def test_cefr_for(rules: Rules) -> None:
    assert cefr_for(-5.0, rules) == "A1"
    assert cefr_for(-1.8, rules) == "A2"  # a cutpoint belongs to the level above
    assert cefr_for(0.0, rules) == "B1"
    assert cefr_for(9.0, rules) == "C2"


def test_no_answers(bank: ItemBank, rules: Rules) -> None:
    assert fit_ability([], bank, rules) == pytest.approx(rules.elo.initial_ability, abs=0.01)
    assert standard_error(0.0, [], bank, rules) == pytest.approx(1.5)
    assert not finished([], bank, rules)


def test_fit_moves_with_answers(bank: ItemBank, rules: Rules) -> None:
    items = bank.items[:10]
    right = [GrammarAnswer(i.id, True) for i in items]
    wrong = [GrammarAnswer(i.id, False) for i in items]
    assert fit_ability(wrong, bank, rules) < 0 < fit_ability(right, bank, rules)
    # Order does not matter.
    mixed = right[:5] + wrong[5:]
    assert fit_ability(mixed, bank, rules) == fit_ability(mixed[::-1], bank, rules)


def test_standard_error_shrinks(bank: ItemBank, rules: Rules) -> None:
    answers = [GrammarAnswer(i.id, True) for i in bank.items if i.cefr == "B1"]
    errors = [standard_error(-0.5, answers[:n], bank, rules) for n in (0, 5, 10, 20)]
    assert errors == sorted(errors, reverse=True)


def test_unknown_item(bank: ItemBank, rules: Rules) -> None:
    with pytest.raises(ValueError, match=r"unknown item p\.nope\.1"):
        fit_ability([GrammarAnswer("p.nope.1", True)], bank, rules)


def test_pick_item_avoids_repeats(bank: ItemBank, rules: Rules) -> None:
    rng = random.Random(0)
    answers: list[GrammarAnswer] = []
    for _ in range(30):
        item = pick_item(answers, bank, rules, rng)
        assert item is not None
        answers.append(GrammarAnswer(item.id, True))
    ids = [a.item_id for a in answers]
    assert len(set(ids)) == len(ids)
    kcs = [bank.get(i).kc for i in ids]  # type: ignore[union-attr]
    assert len(set(kcs)) == len(kcs)  # a KC comes back only once all KCs are used


def test_pick_item_targets_the_learner(bank: ItemBank, rules: Rules) -> None:
    rng = random.Random(0)
    strong = [GrammarAnswer(i.id, True) for i in bank.items if i.cefr in ("B2", "C1")][:8]
    weak = [GrammarAnswer(i.id, False) for i in bank.items if i.cefr in ("A1", "A2")][:8]
    hard = pick_item(strong, bank, rules, rng)
    easy = pick_item(weak, bank, rules, rng)
    assert hard is not None and easy is not None
    assert hard.difficulty > easy.difficulty


def test_pick_item_exhausts_bank(bank: ItemBank, rules: Rules) -> None:
    everything = [GrammarAnswer(i.id, True) for i in bank.items]
    assert pick_item(everything, bank, rules, random.Random(0)) is None
    assert finished(everything, bank, rules)


def test_same_seed_same_test(bank: ItemBank, rules: Rules) -> None:
    assert run(0.0, bank, rules, seed=3) == run(0.0, bank, rules, seed=3)


def test_length_bounds(bank: ItemBank, rules: Rules) -> None:
    for level, ability in TRUE_ABILITY.items():
        n = len(run(ability, bank, rules, seed=1))
        assert 8 <= n <= 20, level


@pytest.mark.parametrize("level", CEFR_LEVELS)
def test_places_simulated_learner(bank: ItemBank, rules: Rules, level: CefrLevel) -> None:
    """A learner in the middle of a level is placed within one level of it, nearly always."""
    placed = [
        CEFR_LEVELS.index(result(run(TRUE_ABILITY[level], bank, rules, s), bank, rules).cefr)
        for s in range(30)
    ]
    within_one = sum(abs(p - CEFR_LEVELS.index(level)) <= 1 for p in placed)
    assert within_one >= 27
    assert statistics.median(placed) == CEFR_LEVELS.index(level)


def test_shipped_cutpoints_follow_the_bank(bank: ItemBank) -> None:
    """Each cutpoint sits near the median difficulty of that level's items."""
    cuts = load_rules().placement.grammar.cefr_cutpoints
    for level, cut in cuts.items():
        median = statistics.median(i.difficulty for i in bank.items if i.cefr == level)
        assert abs(cut - median) <= 0.3, level
