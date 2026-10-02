"""The `exercise_grade` call: its messages and the code check on its output (ADR 0021 §6)."""

from typing import Any

import pytest

from app.adaptive.exercise.formats import FindFixResponse, TextResponse, parse_body
from app.adaptive.exercise.grader import (
    Graded,
    OtherMistake,
    grade_messages,
    system_prompt,
    verdict,
)
from app.adaptive.kc.catalog import get_grammar_catalog

CATALOG = get_grammar_catalog()
KC_ID = "g.present_simple_third_person"
_KC = CATALOG.get(KC_ID)
assert _KC is not None
KC = _KC
OTHER_ID = next(kc.id for kc in CATALOG.kcs if kc.id != KC_ID)


def mistake(kc_id: str = OTHER_ID, original: str = "a", **kw: Any) -> OtherMistake:
    fields: dict[str, Any] = {
        "kc_id": kc_id,
        "error_type": "wrong_form",
        "severity": "medium",
        "original": original,
        "correction": "the",
    }
    return OtherMistake(**(fields | kw))


def test_system_prompt_carries_the_catalog() -> None:
    prompt = system_prompt()
    assert "## Grammar catalog" in prompt
    assert all(kc.id in prompt for kc in CATALOG.kcs)


def test_messages_for_an_open_format() -> None:
    body = parse_body(
        "translate",
        {"source": "她走路上班。", "instruction": "Use the present simple."},
        {"accepted": ["She walks to work."], "explanation": "e"},
    )
    system, human = grade_messages(body, KC, TextResponse(text="She walk to work."), "zh")
    assert system.content == system_prompt()
    text = str(human.content)
    assert "Simplified Chinese" in text
    assert KC_ID in text and KC.description in text
    assert "她走路上班。" in text and "She walks to work." in text
    assert text.endswith("Learner's answer:\nShe walk to work.")


def test_messages_hide_the_evidence_id_of_an_own_sentence() -> None:
    body = parse_body(
        "rewrite_own",
        {"instruction": "Correct it.", "original": "She like tea.", "evidence_id": 42},
        {"accepted": ["She likes tea."], "explanation": "e"},
    )
    text = str(grade_messages(body, KC, TextResponse(text="She likes tea."), "en")[1].content)
    assert "evidence_id" not in text and "42" not in text
    assert "Write the explanation in: English" in text


def test_find_fix_sends_whole_sentences() -> None:
    body = parse_body(
        "find_fix",
        {"segments": ["He ", "go ", "to work."]},
        {"wrong_segment": 1, "accepted": ["goes "], "explanation": "e"},
    )
    response = FindFixResponse(segment=1, fix="is going ")
    text = str(grade_messages(body, KC, response, "zh")[1].content)
    assert "He goes to work." in text
    assert text.endswith("Learner's answer:\nHe is going to work.")


def test_verdict_keeps_other_catalog_kcs_once() -> None:
    graded = Graded(
        correct=True,
        explanation=" Right. ",
        corrected=" ",
        other_mistakes=[
            mistake(),
            mistake(original=" A "),  # the same error again
            mistake(original="an"),
            mistake(kc_id=KC_ID),  # the tested point: the verdict covers it
            mistake(kc_id="g.no_such_point"),
            mistake(original="  "),
        ],
    )
    v = verdict(graded, KC, CATALOG)
    assert v.correct and v.explanation == "Right." and v.corrected is None
    assert [m.original for m in v.other_mistakes] == ["a", "an"]


@pytest.mark.parametrize("corrected", ["She walks to work.", " She walks to work.\n"])
def test_verdict_keeps_the_correction(corrected: str) -> None:
    graded = Graded(correct=False, explanation="e", corrected=corrected)
    assert verdict(graded, KC, CATALOG).corrected == "She walks to work."
