"""The grading evaluation set and evaluator (task 36.3), with scripted graders."""

from collections.abc import Callable, Sequence
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.adaptive.exercise import grader
from app.adaptive.kc.catalog import get_grammar_catalog
from evals.dataset import load_dataset
from evals.grader import Answer, GraderEval, make_case
from evals.runner import evaluate

DATASET = load_dataset("grader")
CATALOG = get_grammar_catalog()
ANSWERS = {c.id: make_case(c.data, CATALOG) for c in DATASET.cases}


class ScriptedGrader:
    def __init__(self, graded: Callable[[Answer], dict[str, Any]]) -> None:
        self.graded = graded
        self.tasks: set[str] = set()

    async def structured[T: BaseModel](
        self, case_id: str, task: str, schema: type[T], messages: Sequence[BaseMessage]
    ) -> T:
        self.tasks.add(task)
        return schema.model_validate(self.graded(ANSWERS[case_id]))


def mistake(kc_id: str) -> dict[str, str]:
    return {
        "kc_id": kc_id,
        "error_type": "wrong_form",
        "severity": "medium",
        "original": f"wrong {kc_id}",
        "correction": "fixed",
    }


def ideal(a: Answer) -> dict[str, Any]:
    return {
        "correct": a.case.correct,
        "explanation": "scripted",
        "other_mistakes": [mistake(sorted(ids)[0]) for ids in a.other_mistakes],
    }


def test_the_set_covers_both_verdicts_in_every_model_graded_format() -> None:
    by_format: dict[str, set[bool]] = {}
    for a in ANSWERS.values():
        by_format.setdefault(a.body.format, set()).add(a.case.correct)
    assert set(by_format) == {"find_fix", "transform", "translate", "rewrite_own"}
    assert all(v == {True, False} for v in by_format.values())
    assert len(ANSWERS) >= 20
    assert sum(bool(a.other_mistakes) for a in ANSWERS.values()) >= 4
    assert set(DATASET.thresholds) == {"verdict_right"}


async def test_an_ideal_grader_gets_everything_right() -> None:
    scripted = ScriptedGrader(ideal)
    report = await evaluate(GraderEval(), scripted, DATASET)
    assert report.met, report.render()
    assert all(r.passed for r in report.results)
    assert scripted.tasks == {grader.TASK}
    names = {m.name for m in report.metrics}
    assert names == {"verdict_right", "other_mistakes_found", "no_extra_mistakes"}


async def test_a_grader_that_passes_everything_fails() -> None:
    report = await evaluate(
        GraderEval(),
        ScriptedGrader(lambda a: {"correct": True, "explanation": "fine"}),
        DATASET,
    )
    by_name = {m.name: m for m in report.metrics}
    assert by_name["verdict_right"].hits == sum(a.case.correct for a in ANSWERS.values())
    assert by_name["other_mistakes_found"].hits == 0
    assert not report.met


async def test_mistakes_on_the_tested_or_an_unknown_kc_are_not_extra() -> None:
    def noisy(a: Answer) -> dict[str, Any]:
        out = ideal(a)
        out["other_mistakes"] += [mistake(a.kc.id), mistake("g.not_in_catalog")]
        return out

    report = await evaluate(GraderEval(), ScriptedGrader(noisy), DATASET)
    assert all(r.passed for r in report.results), report.render()


async def test_an_extra_mistake_on_a_right_answer_is_reported() -> None:
    def extra(a: Answer) -> dict[str, Any]:
        out = ideal(a)
        if a.case.correct and not a.other_mistakes:
            out["other_mistakes"] = [mistake("g.word_order_svo")]
        return out

    report = await evaluate(GraderEval(), ScriptedGrader(extra), DATASET)
    by_name = {m.name: m for m in report.metrics}
    assert by_name["no_extra_mistakes"].hits == 0
    # Not gated: the verdicts are all right, so the set still passes.
    assert report.met
    assert "g.word_order_svo ('wrong g.word_order_svo' -> 'fixed')" in report.render()


def test_cases_code_settles_or_mislabels_are_refused() -> None:
    data = DATASET.cases[0].data
    accepted = data["item"]["answer"]["accepted"][0]
    with pytest.raises(ValueError, match="never reaches the model"):
        make_case({**data, "response": {"text": accepted.upper()}}, CATALOG)
    with pytest.raises(ValueError, match="other than the tested one"):
        make_case({**data, "other_mistakes": [data["item"]["kc"]]}, CATALOG)
    with pytest.raises(ValueError, match="unknown or empty"):
        make_case({**data, "other_mistakes": [["g.nope"]]}, CATALOG)
