"""The grading evaluator (task 36.3): `grade_messages` -> `exercise_grade` -> `verdict`.

Each case is an answer code leaves to the model; `make_case` refuses one code would
settle, so the set never tests a path the app does not take. Every case counts towards
`verdict_right`. Answers with known other mistakes count towards
`other_mistakes_found` (each one tagged with an acceptable KC), and right answers with
none towards `no_extra_mistakes`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.adaptive.exercise import grader
from app.adaptive.exercise.formats import ExerciseBody, Format, Response, parse_body, parse_response
from app.adaptive.exercise.grading import grade
from app.adaptive.exercise.inputs import ExplainIn
from app.adaptive.kc.catalog import GrammarCatalog, GrammarKC, get_grammar_catalog
from evals.dataset import Case
from evals.models import EvalModel
from evals.report import CaseResult


class ItemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Format
    kc: str
    content: dict[str, Any]
    answer: dict[str, Any]


class GraderCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item: ItemSpec
    response: dict[str, Any]
    correct: bool
    other_mistakes: list[str | list[str]] = []
    explain_in: ExplainIn = "zh"


@dataclass(frozen=True, slots=True)
class Answer:
    case: GraderCase
    kc: GrammarKC
    body: ExerciseBody
    response: Response
    # Per expected other mistake, the KC ids that count as finding it.
    other_mistakes: Sequence[frozenset[str]]


def make_case(data: Mapping[str, Any], catalog: GrammarCatalog) -> Answer:
    case = GraderCase.model_validate(data)
    kc = catalog.get(case.item.kc)
    if kc is None:
        raise ValueError(f"unknown grammar KC {case.item.kc}")
    content = dict(case.item.content)
    if case.item.format == "rewrite_own":
        content.setdefault("evidence_id", 1)
    body = parse_body(case.item.format, content, case.item.answer)
    response = parse_response(case.item.format, case.response)
    if not grade(body, response).needs_model:
        raise ValueError("code grades this answer by itself; it never reaches the model")
    expected = [frozenset([m] if isinstance(m, str) else m) for m in case.other_mistakes]
    for ids in expected:
        if not ids or ids - {k.id for k in catalog.kcs}:
            raise ValueError(f"other_mistakes: unknown or empty KC ids {sorted(ids)}")
        if kc.id in ids:
            raise ValueError("other_mistakes are about KCs other than the tested one")
    return Answer(case, kc, body, response, expected)


class GraderEval:
    name = "grader"

    def __init__(self, catalog: GrammarCatalog | None = None) -> None:
        self.catalog = catalog or get_grammar_catalog()

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        a = make_case(case.data, self.catalog)
        graded = await model.structured(
            case.id,
            grader.TASK,
            grader.Graded,
            grader.grade_messages(a.body, a.kc, a.response, a.case.explain_in),
        )
        v = grader.verdict(graded, a.kc, self.catalog)
        found = {m.kc_id for m in v.other_mistakes}
        checks = {"verdict_right": v.correct == a.case.correct}
        if a.other_mistakes:
            checks["other_mistakes_found"] = all(ids & found for ids in a.other_mistakes)
        elif a.case.correct:
            checks["no_extra_mistakes"] = not found
        others = ", ".join(
            f"{m.kc_id} ({m.original!r} -> {m.correction!r})" for m in v.other_mistakes
        )
        detail = f"graded {'right' if v.correct else 'wrong'}: {v.explanation}"
        if others:
            detail += f"\nother mistakes: {others}"
        return CaseResult(case.id, checks, detail)
