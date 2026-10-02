"""Grading answers in code (ADR 0021 §6, Q34a, Q34f)."""

import pytest

from app.adaptive.exercise.formats import (
    ChoiceResponse,
    FindFixResponse,
    Format,
    Response,
    TextResponse,
    parse_body,
)
from app.adaptive.exercise.grading import (
    CodeGrade,
    InvalidResponseError,
    Mark,
    grade,
    with_fix,
)

BODIES = {
    "choice4": (
        {"stem": "He ___ here.", "options": ["lives", "live", "living", "is live"]},
        {"correct": "lives", "explanation": "e"},
    ),
    "cloze": (
        {"stem": "She ___ tea.", "hint": "drink"},
        {"accepted": ["drinks", "is drinking"], "explanation": "e"},
    ),
    "find_fix": (
        {"segments": ["He ", "go ", "to work."]},
        {"wrong_segment": 1, "accepted": ["goes "], "explanation": "e"},
    ),
    "translate": (
        {"source": "她走路上班。"},
        {"accepted": ["She walks to work."], "explanation": "e"},
    ),
}


def run(fmt: Format, response: Response) -> CodeGrade:
    content, answer = BODIES[fmt]
    return grade(parse_body(fmt, content, answer), response)


R, P = "recognition", "production"


@pytest.mark.parametrize(
    ("fmt", "response", "expected"),
    [
        ("choice4", ChoiceResponse(choice="lives"), CodeGrade((Mark(R, True),))),
        ("choice4", ChoiceResponse(choice=" Live "), CodeGrade((Mark(R, False),))),
        ("cloze", TextResponse(text="Drinks."), CodeGrade((Mark(R, True),))),
        ("cloze", TextResponse(text="is  drinking"), CodeGrade((Mark(R, True),))),
        ("cloze", TextResponse(text="drink"), CodeGrade((Mark(R, False),))),
        # Q34f: a fix on a piece that was fine is one recognition miss, no production.
        ("find_fix", FindFixResponse(segment=2, fix="to the work."), CodeGrade((Mark(R, False),))),
        (
            "find_fix",
            FindFixResponse(segment=1, fix="goes"),
            CodeGrade((Mark(R, True), Mark(P, True))),
        ),
        ("find_fix", FindFixResponse(segment=1, fix="went"), CodeGrade((Mark(R, True),), True)),
        # Q34a: a reference answer needs no model.
        ("translate", TextResponse(text="she walks to work"), CodeGrade((Mark(P, True),))),
        ("translate", TextResponse(text="She goes to work on foot."), CodeGrade((), True)),
    ],
)
def test_grade(fmt: Format, response: Response, expected: CodeGrade) -> None:
    assert run(fmt, response) == expected


@pytest.mark.parametrize(
    ("fmt", "response"),
    [
        ("choice4", ChoiceResponse(choice="lived")),
        ("choice4", TextResponse(text="lives")),
        ("cloze", ChoiceResponse(choice="drinks")),
        ("find_fix", FindFixResponse(segment=3, fix="x")),
        ("find_fix", TextResponse(text="He goes to work.")),
        ("translate", ChoiceResponse(choice="x")),
    ],
)
def test_answers_that_do_not_fit_are_refused(fmt: Format, response: Response) -> None:
    with pytest.raises(InvalidResponseError):
        run(fmt, response)


def test_with_fix_keeps_the_spacing_of_the_piece() -> None:
    content, answer = BODIES["find_fix"]
    body = parse_body("find_fix", content, answer)
    assert with_fix(body.content, FindFixResponse(segment=1, fix=" went ")) == "He went to work."  # type: ignore[arg-type]
