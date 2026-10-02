"""Grading open answers with a model: `exercise_grade` (ADR 0021 §6).

The model judges only this answer: is the tested structure right, plus the learner's
other grammar mistakes. Mastery stays with BKT over the evidence code writes from the
verdict. Other mistakes are kept only with a catalog KC other than the tested one.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.adaptive.exercise.formats import ExerciseBody, FindFix, FindFixResponse, Response
from app.adaptive.exercise.grading import with_fix
from app.adaptive.exercise.inputs import ExplainIn
from app.adaptive.exercise.messages import shown
from app.adaptive.kc.catalog import ErrorType, GrammarCatalog, GrammarKC, get_grammar_catalog
from app.adaptive.rules import Severity
from app.memory.reflection import render_catalog
from app.prompts import load_prompt

TASK = "exercise_grade"

_LANGUAGES = {"zh": "Simplified Chinese", "en": "English"}


class OtherMistake(BaseModel):
    kc_id: str = Field(description="Grammar KC id from the catalog")
    error_type: ErrorType
    severity: Severity
    original: str = Field(description="The smallest wrong part of the answer, exact")
    correction: str = Field(description="That part corrected")


class Graded(BaseModel):
    correct: bool = Field(description="The answer does the task with the tested structure right")
    explanation: str = Field(description="Feedback on the tested structure, to the learner")
    corrected: str | None = Field(
        None, description="The answer with its grammar mistakes fixed; null if none"
    )
    other_mistakes: list[OtherMistake] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Verdict:
    correct: bool
    explanation: str
    corrected: str | None
    other_mistakes: tuple[OtherMistake, ...]


@cache
def system_prompt() -> str:
    """Instructions plus the catalog: the same on every call, so vendors can cache it."""
    catalog = render_catalog(get_grammar_catalog())
    return f"{load_prompt(TASK)}\n\n## Grammar catalog\n\n{catalog}"


def learner_answer(body: ExerciseBody, response: Response) -> str:
    if isinstance(body, FindFix) and isinstance(response, FindFixResponse):
        return with_fix(body.content, response)
    text = getattr(response, "text", None)
    assert isinstance(text, str), "open formats take a text"
    return text


def grade_messages(
    body: ExerciseBody, kc: GrammarKC, response: Response, explain_in: ExplainIn
) -> list[BaseMessage]:
    item = shown(body)
    if isinstance(body, FindFix):
        # Reached only with the right piece and a fix not in the list (grading.grade):
        # the learner's answer and the references are whole sentences.
        item["task"] = "Find the wrong piece and correct it"
        item["reference_answers"] = [
            with_fix(body.content, FindFixResponse(segment=body.answer.wrong_segment, fix=fix))
            for fix in body.answer.accepted
        ]
    parts = [
        f"Write the explanation in: {_LANGUAGES[explain_in]}",
        f"Tested grammar point: {kc.id} ({kc.name_en}, {kc.cefr}): {kc.description}",
        "Item:\n" + _json(item),
        f"Learner's answer:\n{learner_answer(body, response)}",
    ]
    return [SystemMessage(system_prompt()), HumanMessage("\n\n".join(parts))]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def verdict(graded: Graded, kc: GrammarKC, catalog: GrammarCatalog) -> Verdict:
    """Keep other mistakes on catalog KCs other than the tested one, once each."""
    seen: set[tuple[str, str]] = set()
    kept: list[OtherMistake] = []
    for m in graded.other_mistakes:
        key = (m.kc_id, m.original.strip().casefold())
        if m.kc_id == kc.id or m.kc_id not in catalog or not m.original.strip() or key in seen:
            continue
        seen.add(key)
        kept.append(m)
    corrected = (graded.corrected or "").strip() or None
    return Verdict(graded.correct, graded.explanation.strip(), corrected, tuple(kept))


__all__: Sequence[str] = ("TASK", "Graded", "OtherMistake", "Verdict", "grade_messages", "verdict")
