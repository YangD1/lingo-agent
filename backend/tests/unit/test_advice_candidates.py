"""Ranking the dashboard's candidate study actions (P1 plan §7.5.2)."""

import dataclasses

import pytest

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice.candidates import Example, Signals, WeakKC, rank
from app.services.vocab.books import get_book

RULES = get_rules()
CATALOG = get_grammar_catalog()
BOOK = get_book("cet4")


def kc(kc_id: str) -> WeakKC:
    found = CATALOG.get(kc_id)
    assert found is not None
    return WeakKC(found, 0.3, 1)


# A learner with nothing to suggest: tested lately, book chosen and screened.
SETTLED = Signals(
    reviews_due=0,
    new_left=0,
    book=BOOK,
    screened=True,
    placement_days=3,
    placement_in_progress=False,
    weak_kcs=(),
)


def ids(signals: Signals) -> list[str]:
    return [c.id for c in rank(signals, RULES)]


def test_a_new_learner_is_sent_to_the_test_then_a_book() -> None:
    new = dataclasses.replace(SETTLED, book=None, screened=False, placement_days=None)
    assert ids(new) == ["placement", "choose_book"]
    assert rank(new, RULES)[0].days_since is None


def test_nothing_to_suggest_gives_no_candidates() -> None:
    assert rank(SETTLED, RULES) == []


def test_a_chosen_book_not_screened_yet_suggests_screening() -> None:
    assert ids(dataclasses.replace(SETTLED, screened=False)) == ["vocab_screen"]


@pytest.mark.parametrize(
    ("days", "expected"), [(59, []), (60, ["placement"]), (200, ["placement"])]
)
def test_a_retest_after_sixty_days(days: int, expected: list[str]) -> None:
    signals = dataclasses.replace(SETTLED, placement_days=days)
    assert ids(signals) == expected
    if expected:
        retest = rank(signals, RULES)[0]
        assert retest.days_since == days
        # A retest matters less than a first test.
        assert retest.score == RULES.advice.priority["retest"]


def test_more_due_words_are_more_urgent_but_capped_by_priority() -> None:
    few = rank(dataclasses.replace(SETTLED, reviews_due=2), RULES)[0]
    many = rank(dataclasses.replace(SETTLED, reviews_due=200), RULES)[0]
    assert (few.kind, few.count, many.count) == ("vocab_review", 2, 200)
    assert few.score < many.score < RULES.advice.priority["vocab_review"]


def test_grammar_ranks_by_mistakes_and_distance_from_mastered() -> None:
    weak = [
        dataclasses.replace(kc("g.articles_basic"), mistakes=1, p_mastery=0.5),
        dataclasses.replace(kc("g.present_simple_third_person"), mistakes=3, p_mastery=0.2),
        dataclasses.replace(
            kc("g.past_simple_irregular"),
            mistakes=2,
            p_mastery=0.3,
            examples=(Example("a", "b"), Example("c", "d"), Example("e", "f")),
        ),
        # Mastered despite a slip: nothing to practise.
        dataclasses.replace(kc("g.plural_nouns"), mistakes=4, p_mastery=RULES.bkt.mastered),
    ]
    found = rank(dataclasses.replace(SETTLED, weak_kcs=tuple(weak)), RULES)

    # At most `max_grammar` KCs, the one with the most weighted mistakes first.
    assert [c.id for c in found] == [
        "grammar_practice:g.present_simple_third_person",
        "grammar_practice:g.past_simple_irregular",
    ]
    assert found[0].kc is not None and found[0].count == 3 and found[0].p_mastery == 0.2
    assert len(found[1].examples) == 2


def test_candidates_are_cut_to_the_limit_best_first() -> None:
    busy = Signals(
        reviews_due=40,
        new_left=15,
        book=None,
        screened=False,
        placement_days=None,
        placement_in_progress=True,
        weak_kcs=(
            kc("g.articles_basic"),
            kc("g.present_simple_third_person"),
            kc("g.past_simple_irregular"),
        ),
    )
    found = rank(busy, RULES)

    assert len(found) == RULES.advice.max_candidates
    assert [c.score for c in found] == sorted((c.score for c in found), reverse=True)
    assert found[0].id == "placement" and found[0].in_progress
    assert len({c.id for c in found}) == len(found)
    assert sum(c.kind == "grammar_practice" for c in found) <= RULES.advice.max_grammar
