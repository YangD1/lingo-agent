"""How a quiz's questions read in the tutor's context (ADR 0051)."""

from app.adaptive.exercise.formats import parse_body
from app.cards.quiz import QuizItem, QuizState, _choices


def test_each_format_shows_what_the_card_shows() -> None:
    cloze = parse_body(
        "cloze",
        {"stem": "She ___ here.", "hint": "live"},
        {"accepted": ["lives"], "explanation": "Third person."},
    )
    find_fix = parse_body(
        "find_fix",
        {"segments": ["She ", "live ", "here."]},
        {"wrong_segment": 1, "accepted": ["lives "], "explanation": "Third person."},
    )
    assert _choices(cloze) == "hint: 'live'"
    assert _choices(find_fix) == "pieces: [0] 'She ' [1] 'live ' [2] 'here.'"


def test_questions_are_listed_only_when_asked_for() -> None:
    state = QuizState(
        "in_progress",
        2,
        1,
        0,
        (
            QuizItem("She ___ here.", "hint: 'live'", "lives", given="live", correct=False),
            QuizItem("He ___ tea.", "", "drinks"),
        ),
    )

    assert state.describe("quiz", 0.8) == "1 of 2 answered so far"
    listed = state.describe("quiz", 0.8, questions=True)
    assert listed.splitlines()[1:] == [
        "    1. 'She ___ here.'; hint: 'live'; they answered 'live' (wrong); key: 'lives'",
        "    2. 'He ___ tea.'; not answered yet; key (say it only if they ask): 'drinks'",
    ]
    assert state.wrong == (("She ___ here.", "live", "lives"),)


def test_a_finished_listed_quiz_does_not_repeat_its_misses() -> None:
    state = QuizState("done", 1, 1, 0, (QuizItem("Q", "", "k", given="x", correct=False),))
    assert "missed:" in state.describe("check", 0.8)
    assert "missed:" not in state.describe("check", 0.8, questions=True)
