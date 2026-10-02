"""Bank items for slots the generator could not fill (ADR 0021 §3, Q33c)."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.adaptive.exercise import bank, planner
from app.adaptive.exercise.bank import Slot
from app.adaptive.exercise.planner import target_difficulty
from app.adaptive.kc.catalog import CefrLevel, get_grammar_catalog
from app.adaptive.placement.items import Item, ItemBank, get_item_bank
from app.adaptive.rules import get_rules

CATALOG, RULES = get_grammar_catalog(), get_rules()
NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
ABILITY = -1.0
TARGET = target_difficulty(ABILITY, "choice4", RULES)


def item(item_id: str, kc: str, offset: float = 0.0) -> Item:
    return Item(
        id=item_id,
        kc=kc,
        cefr="A2",
        stem="She ___ here.",
        answer="lives",
        distractors=("live", "living", "is live"),
        ratings={},
        difficulty=TARGET + offset,
    )


BANK = ItemBank(
    format="choice4",
    items=(
        item("a.near", "g.a", 0.1),
        item("a.far", "g.a", 1.5),
        item("b.1", "g.b", 0.0),
        item("c.1", "g.c", 0.2),
        item("d.1", "g.d", 0.0),
    ),
)


def fill(
    slots: list[Slot],
    *,
    seen: dict[str, datetime] | None = None,
    weak: tuple[str, ...] = (),
    wider: tuple[str, ...] = (),
    neighbours: dict[int, str] | None = None,
) -> dict[int, str]:
    found = bank.fill(
        slots,
        neighbours=neighbours or {},
        weak_kcs=weak,
        wider_kcs=wider,
        bank=BANK,
        seen=seen or {},
        ability=ABILITY,
        now=NOW,
        rules=RULES,
    )
    return {position: i.id for position, i in found.items()}


def test_same_kc_unseen_nearest_the_target_first() -> None:
    assert fill([Slot(0, "g.a")]) == {0: "a.near"}


def test_seen_items_wait_for_the_repeat_interval() -> None:
    recently = NOW - timedelta(days=RULES.practice.bank_repeat_days - 1)
    long_ago = NOW - timedelta(days=RULES.practice.bank_repeat_days)
    assert fill([Slot(0, "g.a")], seen={"a.near": recently}) == {0: "a.far"}
    both = {"a.near": recently, "a.far": long_ago}
    assert fill([Slot(0, "g.a")], seen=both) == {0: "a.far"}
    assert fill([Slot(0, "g.a")], seen={"a.near": recently, "a.far": recently}) == {}


def test_other_weak_kcs_stand_in_unseen_first() -> None:
    seen = {"a.near": NOW, "a.far": NOW, "b.1": NOW - timedelta(days=30)}
    assert fill([Slot(0, "g.a")], seen=seen, weak=("g.b", "g.c")) == {0: "c.1"}
    seen["c.1"] = NOW
    assert fill([Slot(0, "g.a")], seen=seen, weak=("g.b", "g.c")) == {0: "b.1"}


def test_a_stand_in_avoids_the_kc_next_to_it() -> None:
    found = fill([Slot(1, "g.z")], weak=("g.b", "g.d"), neighbours={0: "g.b", 2: "g.x"})
    assert found == {1: "d.1"}


def test_items_are_not_used_twice_and_unfillable_slots_are_dropped() -> None:
    found = fill([Slot(0, "g.a"), Slot(1, "g.a"), Slot(2, "g.a"), Slot(3, "g.z")])
    assert found == {0: "a.near", 1: "a.far"}


def test_bank_item_becomes_a_choice4_with_an_explanation() -> None:
    kc = CATALOG.get("g.present_simple_third_person")
    assert kc is not None
    source = item("x", kc.id)
    zh = bank.to_body(source, kc, "zh", random.Random(1))
    assert set(zh.content.options) == set(source.options)
    assert zh.answer.correct == "lives"
    assert kc.name_zh in zh.answer.explanation and "lives" in zh.answer.explanation
    en = bank.to_body(source, kc, "en", random.Random(1))
    assert kc.name_en in en.answer.explanation


def test_every_real_bank_item_converts() -> None:
    for source in get_item_bank().items:
        kc = CATALOG.get(source.kc)
        assert kc is not None
        bank.to_body(source, kc, "zh", random.Random(0))


def test_the_level_window_comes_after_the_set_kcs() -> None:
    old = NOW - timedelta(days=30)
    seen = {"a.near": NOW, "a.far": NOW, "b.1": old}
    # The set's own weak KC, even seen long ago, before a fresh one from the window.
    assert fill([Slot(0, "g.a")], seen=seen, weak=("g.b",), wider=("g.c",)) == {0: "b.1"}
    seen["b.1"] = NOW
    assert fill([Slot(0, "g.a")], seen=seen, weak=("g.b",), wider=("g.d", "g.c")) == {0: "d.1"}


@pytest.mark.parametrize("level", [None, "A1", "B1", "B2", "C1"])
def test_without_a_model_a_whole_set_comes_from_the_bank(level: CefrLevel | None) -> None:
    """Q33g: a set covers about five KCs with about one bank item each; the window's
    other KCs fill the rest."""
    ability = RULES.difficulty.cefr_anchor[level or RULES.practice.default_level]
    for seed in range(20):
        planned = planner.plan(
            CATALOG, {}, learner_level=level, ability=ability, now=NOW, rules=RULES, seed=seed
        )
        ranked = planner.candidates(CATALOG, {}, learner_level=level, now=NOW, rules=RULES)
        found = bank.fill(
            [Slot(i, p.kc_id) for i, p in enumerate(planned)],
            neighbours={},
            weak_kcs=[p.kc_id for p in planned if p.role == "weak"],
            wider_kcs=ranked.weak,
            bank=get_item_bank(),
            seen={},
            ability=ability,
            now=NOW,
            rules=RULES,
        )
        assert len(found) == RULES.practice.set_size
