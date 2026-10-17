"""Spotting a reply that gives away an unanswered quiz item's answer (task 95.3)."""

from app.adaptive.exercise.formats import ExerciseBody, parse_body
from app.cards.quiz import revealed

WHY = "Third person."


def choice(correct: str = "plays", *others: str) -> ExerciseBody:
    options = [correct, *(others or ("play", "playing", "played"))]
    return parse_body(
        "choice4",
        {"stem": "He ___ football.", "options": options},
        {"correct": correct, "explanation": WHY},
    )


def cloze(accepted: str = "lives", stem: str = "She ___ here.") -> ExerciseBody:
    return parse_body(
        "cloze", {"stem": stem, "hint": "live"}, {"accepted": [accepted], "explanation": WHY}
    )


def test_each_format_is_caught_by_its_answer() -> None:
    items = {
        1: choice(),
        2: cloze(),
        3: parse_body(
            "find_fix",
            {"segments": ["She ", "live ", "here."]},
            {"wrong_segment": 1, "accepted": ["lives "], "explanation": WHY},
        ),
        4: parse_body(
            "transform",
            {"instruction": "Make it negative.", "source": "He likes tea."},
            {"accepted": ["He doesn't like tea."], "explanation": WHY},
        ),
        5: parse_body(
            "translate",
            {"source": "她每天读书。"},
            {"accepted": ["She reads every day."], "explanation": WHY},
        ),
    }
    assert revealed("第一题选 plays 就对了", items) == [1]
    assert revealed("答案是lives。", items) == [2, 3]
    assert revealed("可以写成 he doesn\u2019t like tea", items) == [4]
    assert revealed("She reads every day!", items) == [5]
    assert revealed("想想主语是第三人称单数时动词要怎么变。", items) == []


def test_whole_words_only() -> None:
    assert revealed("He replays it.", {1: choice()}) == []
    assert revealed("Olives are nice.", {1: cloze()}) == []


def test_listing_every_option_gives_nothing_away() -> None:
    assert revealed("选项有 plays、play、playing 和 played。", {1: choice()}) == []
    assert revealed("不是 play、也不是 playing、是 plays。", {1: choice()}) == [1]


def test_words_the_card_already_shows_do_not_count() -> None:
    item = cloze(accepted="home", stem="I go home after ___ .")
    assert revealed("Look at 'home' in the sentence.", {1: item}) == []


def test_a_short_answer_counts_only_when_set_off() -> None:
    item = cloze(accepted="an", stem="She is ___ engineer.")
    assert revealed("an 和 a 的区别看后面的发音。", {1: item}) == []
    assert revealed("这里填 **an**。", {1: item}) == [1]
    assert revealed('填 "an"', {1: item}) == [1]


def test_checks_are_not_looked_at() -> None:
    check = parse_body(
        "concept_choice",
        {"question": "When does the verb take -s?", "options": ["he", "I", "we", "you"]},
        {"correct": "he", "explanation": WHY},
    )
    assert revealed("**he**", {1: check}) == []
