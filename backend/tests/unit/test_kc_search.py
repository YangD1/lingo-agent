"""Finding grammar KCs by name (ADR 0046 §1)."""

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.kc.search import find_kcs, is_clear


def best(topic: str, within: list[str] | None = None) -> str | None:
    matches = find_kcs(get_grammar_catalog(), topic, within)
    return matches[0].kc.id if is_clear(matches) else None


def candidates(topic: str) -> list[str]:
    matches = find_kcs(get_grammar_catalog(), topic)
    assert not is_clear(matches)
    return [m.kc.id for m in matches]


def test_a_clear_name_finds_its_point() -> None:
    assert best("subject + verb word order") == "g.word_order_svo"
    assert best("passive voice") == "g.passive_basic"
    assert best("third person -s") == "g.present_simple_third_person"


def test_ids_and_exact_names_win_outright() -> None:
    assert best("g.be_present") == "g.be_present"
    assert best("be_present") == "g.be_present"
    assert best("First conditional") == "g.first_conditional"
    assert best("名词复数") == "g.plural_nouns"


def test_chinese_names_match() -> None:
    assert best("比较级") == "g.comparatives"


def test_a_broad_name_gives_candidates() -> None:
    found = candidates("present perfect")
    assert {"g.present_perfect_experience", "g.present_perfect_for_since"} <= set(found)
    assert "g.word_order_svo" in candidates("主语 + 动词")[:5]


def test_nothing_matches_unrelated_words() -> None:
    assert find_kcs(get_grammar_catalog(), "photosynthesis") == []
    assert find_kcs(get_grammar_catalog(), "the grammar") == []


def test_within_limits_the_search() -> None:
    assert best("present perfect", ["g.present_perfect_for_since"]) == (
        "g.present_perfect_for_since"
    )
    assert find_kcs(get_grammar_catalog(), "passive voice", ["g.be_present"]) == []
