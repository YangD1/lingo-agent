"""Grading what code can grade (ADR 0021 §6, Q34a, Q34f).

`grade` turns a learner's answer into observations on the item's KC. Closed formats
are settled here. find_fix is settled when the piece is wrong (one recognition miss:
fixing a piece that was fine says nothing about producing the fix, Q34f) or the fix is
on the list; otherwise the fix goes to the grading model. Open answers matching a
reference answer (after `normalize`) are right without a model call (Q34a).
"""

from dataclasses import dataclass

from app.adaptive.exercise.formats import (
    Choice4,
    ChoiceResponse,
    Cloze,
    ExerciseBody,
    FindFix,
    FindFixContent,
    FindFixResponse,
    Response,
    TextResponse,
    normalize,
)
from app.adaptive.rules import Evidence


class InvalidResponseError(ValueError):
    """The answer does not fit the item (wrong shape, an option not offered, ...)."""


@dataclass(frozen=True, slots=True)
class Mark:
    """One observation on the item's KC."""

    evidence: Evidence
    correct: bool


@dataclass(frozen=True, slots=True)
class CodeGrade:
    marks: tuple[Mark, ...]
    # The production part still waits for `exercise_grade`; the model's verdict adds
    # one production mark.
    needs_model: bool = False


def _in(text: str, accepted: tuple[str, ...]) -> bool:
    return normalize(text) in {normalize(a) for a in accepted}


def with_fix(content: FindFixContent, response: FindFixResponse) -> str:
    """The learner's sentence: the chosen piece replaced by their fix, spacing kept."""
    pieces = list(content.segments)
    old = pieces[response.segment]
    # Pieces carry their own surrounding spaces; keep them around the fix.
    lead = old[: len(old) - len(old.lstrip())]
    trail = old[len(old.rstrip()) :]
    pieces[response.segment] = f"{lead}{response.fix.strip()}{trail}"
    return "".join(pieces)


def grade(body: ExerciseBody, response: Response) -> CodeGrade:
    match body, response:
        case Choice4(), ChoiceResponse():
            if not _in(response.choice, body.content.options):
                raise InvalidResponseError("not one of the options")
            return CodeGrade((Mark("recognition", _in(response.choice, (body.answer.correct,))),))
        case Cloze(), TextResponse():
            return CodeGrade((Mark("recognition", _in(response.text, body.answer.accepted)),))
        case FindFix(), FindFixResponse():
            if response.segment >= len(body.content.segments):
                raise InvalidResponseError("no such piece")
            if response.segment != body.answer.wrong_segment:
                return CodeGrade((Mark("recognition", False),))
            spotted = Mark("recognition", True)
            if _in(response.fix, body.answer.accepted):
                return CodeGrade((spotted, Mark("production", True)))
            return CodeGrade((spotted,), needs_model=True)
        case FindFix(), _:
            raise InvalidResponseError("find_fix takes a piece and a fix")
        case Choice4(), _:
            raise InvalidResponseError("choice4 takes a choice")
        case Cloze(), _:
            raise InvalidResponseError("cloze takes a text")
        case _, TextResponse():
            if _in(response.text, body.answer.accepted):
                return CodeGrade((Mark("production", True),))
            return CodeGrade((), needs_model=True)
        case _:
            raise InvalidResponseError(f"{body.format} takes a text")
