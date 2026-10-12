from langchain_core.messages import AIMessage, HumanMessage

from app.prompts import load_prompt
from app.speaking.summary import (
    TASK,
    Mistake,
    Natural,
    SpeakingSummary,
    check,
    summary_messages,
)

SAID = ["By the way, what does the word serendipity mean?", "Yesterday I goed home."]


def summary(mistakes: list[Mistake], natural: list[Natural]) -> SpeakingSummary:
    return SpeakingSummary(
        went_well=[],
        mistakes=mistakes,
        more_natural=natural,
        next_expressions=[],
        intelligibility="mostly",
    )


def test_changes_of_punctuation_or_case_alone_are_dropped() -> None:
    """Task 64.2: speech has no quotation marks to correct (Q64w)."""
    stored = check(
        summary(
            [
                Mistake(
                    quote="what does the word serendipity mean?",
                    correction="What does the word 'serendipity' mean?",
                    explanation="quotes",
                ),
                Mistake(quote="I goed home", correction="I went home", explanation="past"),
            ],
            [
                Natural(
                    quote="By the way, what does the word serendipity mean?",
                    natural="By the way - what does the word “serendipity” mean?",
                    note="",
                ),
                Natural(
                    quote="what does the word serendipity mean",
                    natural="what does serendipity mean",
                    note="shorter",
                ),
            ],
        ),
        SAID,
    )
    assert [m["correction"] for m in stored["mistakes"]] == ["I went home"]
    assert [n["natural"] for n in stored["more_natural"]] == ["what does serendipity mean"]


def test_a_call_tells_the_model_its_turns_break_at_pauses() -> None:
    messages = [HumanMessage("Like playing football."), AIMessage("Nice!")]

    cascade = summary_messages(messages, scenario=None, level="B1", explain_in="zh")
    call = summary_messages(messages, scenario=None, level="B1", explain_in="zh", call=True)

    note = load_prompt(f"{TASK}_call")
    assert note not in cascade[0].text
    assert call[0].text.endswith(note)
    assert call[1].text == cascade[1].text


def test_in_a_call_a_fix_that_only_mends_a_cut_is_dropped() -> None:
    said = ["Hi. My name is Tom.", "Like playing football.", "I from Chengdu. I went", "home."]
    natural = [
        Natural(quote="Like playing football", natural="I like playing football", note=""),
        Natural(quote="I went", natural="I went home yesterday", note=""),
    ]
    mistakes = [Mistake(quote="I from Chengdu", correction="I'm from Chengdu", explanation="")]

    call = check(summary(mistakes, natural), said, call=True)
    cascade = check(summary(mistakes, natural), said)

    assert [m["quote"] for m in call["mistakes"]] == ["I from Chengdu"]
    assert call["more_natural"] == []
    # Said in one go, a missing subject is the learner's.
    assert len(cascade["more_natural"]) == 2
