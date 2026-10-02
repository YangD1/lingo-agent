from collections import Counter
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest

from app.adaptive.elo import expected, guess_for
from app.adaptive.exercise.formats import FORMATS
from app.adaptive.exercise.planner import (
    PRODUCTION,
    RECOGNITION,
    KCState,
    PlannedItem,
    plan,
    target_difficulty,
)
from app.adaptive.kc.catalog import GrammarCatalog, get_grammar_catalog
from app.adaptive.rules import get_rules

CATALOG, RULES = get_grammar_catalog(), get_rules()
NOW = datetime(2026, 10, 2, 9, tzinfo=UTC)
A1 = [kc.id for kc in CATALOG.kcs if kc.cefr == "A1"]
C2 = next(kc.id for kc in CATALOG.kcs if kc.cefr == "C2")


def small_catalog(n: int) -> GrammarCatalog:
    kcs = [
        {"id": f"g.k{i}", "name_en": "K", "name_zh": "K", "cefr": "A1", "description": "x"}
        for i in range(n)
    ]
    return GrammarCatalog.model_validate({"kcs": kcs})


def learned(due_in_days: float, p: float = 0.97) -> KCState:
    return KCState(p_mastery=p, learned=True, due=NOW + timedelta(days=due_in_days))


def run(states: dict[str, KCState] | None = None, seed: int = 1, **kw: Any) -> list[PlannedItem]:
    catalog = kw.pop("catalog", CATALOG)
    args: dict[str, Any] = {
        "learner_level": "A2",
        "ability": 0.0,
        "now": NOW,
        "rules": RULES,
        "seed": seed,
    } | kw
    return plan(catalog, states or {}, **args)


def test_formats_split_into_recognition_and_production() -> None:
    assert set(RECOGNITION) | set(PRODUCTION) == set(FORMATS)
    assert not set(RECOGNITION) & set(PRODUCTION)


def test_full_set_mostly_weak_with_some_review() -> None:
    states = {A1[0]: learned(-1), A1[1]: learned(-2), A1[2]: learned(5), A1[3]: learned(9)}
    items = run(states)
    assert len(items) == RULES.practice.set_size
    roles = Counter(i.role for i in items)
    assert roles["review"] == round(RULES.practice.set_size * (1 - RULES.practice.weak_share))
    assert {i.kc_id for i in items if i.role == "review"} == {A1[1], A1[0], A1[2]}


def test_due_learned_kcs_come_first() -> None:
    states = {A1[0]: learned(30), A1[1]: learned(-3), A1[2]: learned(-1), A1[3]: learned(2)}
    items = run(states)
    review = {i.kc_id for i in items if i.role == "review"}
    assert review == {A1[1], A1[2], A1[3]}  # the one due in 30 days waits


def test_without_learned_kcs_the_whole_set_is_weak() -> None:
    items = run()
    assert len(items) == RULES.practice.set_size
    assert {i.role for i in items} == {"weak"}


@pytest.mark.parametrize("seed", range(25))
def test_interleaving_rules_hold(seed: int) -> None:
    states = {A1[0]: learned(-1), A1[1]: learned(-1)}
    items = run(states, seed=seed)
    run_max = RULES.practice.max_same_format_run
    for a, b in pairwise(items):
        assert a.kc_id != b.kc_id
    for i in range(len(items) - run_max):
        window = items[i : i + run_max + 1]
        assert len({w.format for w in window}) > 1
    per_kc = Counter(i.kc_id for i in items)
    assert max(per_kc.values()) <= RULES.practice.max_items_per_kc
    # Several formats per KC, never the same twice for one KC in one set.
    assert all(len({i.format for i in items if i.kc_id == k}) == n for k, n in per_kc.items())


def test_same_seed_same_plan() -> None:
    assert run(seed=7) == run(seed=7)


def formats_of(items: list[PlannedItem], kc_id: str) -> list[str]:
    return [i.format for i in items if i.kc_id == kc_id]


def test_weak_kcs_get_recognition_first_strong_ones_production() -> None:
    states = {"g.k0": KCState(p_mastery=0.1), "g.k1": KCState(p_mastery=0.6)}
    items = run(states, learner_level="A1", catalog=small_catalog(2))
    assert set(formats_of(items, "g.k0")) == set(RECOGNITION)
    # Without an own sentence there are two production formats, then recognition.
    assert {"transform", "translate"} <= set(formats_of(items, "g.k1"))


def test_rewrite_own_needs_an_own_sentence() -> None:
    catalog = small_catalog(3)
    strong = {f"g.k{i}": KCState(p_mastery=0.6) for i in range(3)}
    assert "rewrite_own" not in {i.format for i in run(strong, catalog=catalog)}
    own = {k: KCState(p_mastery=0.6, has_own_sentence=True) for k in strong}
    with_own = run(own, catalog=catalog)
    assert all("rewrite_own" in formats_of(with_own, k) for k in own)


def test_unpassed_formats_first() -> None:
    passed = frozenset({"choice4", "cloze"})
    states = {"g.k0": KCState(p_mastery=0.2, formats_passed=passed)}
    for seed in range(5):
        items = run(states, seed=seed, learner_level="A1", catalog=small_catalog(4))
        assert "find_fix" in formats_of(items, "g.k0")


def test_recent_mistakes_raise_priority() -> None:
    catalog = small_catalog(8)
    states = {f"g.k{i}": KCState(p_mastery=0.3) for i in range(8)}
    states["g.k7"] = KCState(p_mastery=0.3, recent_mistakes=4)
    items = run(states, catalog=catalog, learner_level="A1")
    # Ten weak items, about two per KC: the five highest-priority KCs; ties by id.
    assert {i.kc_id for i in items} == {"g.k7", "g.k0", "g.k1", "g.k2", "g.k3"}


def test_diagnosis_boost_lifts_a_kc() -> None:
    states = {f"g.k{i}": KCState(p_mastery=0.3) for i in range(8)}
    items = run(states, catalog=small_catalog(8), learner_level="A1", boost={"g.k6": 3.0})
    assert "g.k6" in {i.kc_id for i in items}
    assert "g.k6" not in {i.kc_id for i in run(states, catalog=small_catalog(8))}


def test_out_of_window_kcs_only_with_evidence() -> None:
    assert C2 not in {i.kc_id for i in run(learner_level="A2")}
    states = {C2: KCState(p_mastery=0.05, recent_mistakes=10)}
    assert C2 in {i.kc_id for i in run(states, learner_level="A2")}


def test_unknown_level_uses_the_default() -> None:
    assert run(learner_level=None, seed=3) == run(learner_level=None, seed=3)
    levels = {CATALOG.get(i.kc_id).cefr for i in run(learner_level=None)}  # type: ignore[union-attr]
    assert levels <= {"A1", "A2", "B1"}


def test_small_catalog_gives_a_shorter_set() -> None:
    items = run(learner_level="A1", catalog=small_catalog(2))
    assert len(items) == 2 * RULES.practice.max_items_per_kc


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("ability", [-2.0, 0.0, 1.5])
def test_target_difficulty_hits_the_target_chance(fmt: str, ability: float) -> None:
    d = target_difficulty(ability, fmt, RULES)  # type: ignore[arg-type]
    target = RULES.practice.target_p
    assert expected(ability, d, guess_for(fmt, RULES)) == pytest.approx(
        (target.low + target.high) / 2
    )
