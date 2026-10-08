"""The diagnosis evaluation set and evaluator (task 46.6), with scripted models."""

from collections.abc import Callable, Sequence
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.adaptive.diagnosis.checks import TASK
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from evals.dataset import load_dataset
from evals.diagnosis import DiagnosisEval, Scenario, make_case
from evals.runner import evaluate

DATASET = load_dataset("diagnosis")
CATALOG, RULES = get_grammar_catalog(), get_rules()
SCENARIOS = {c.id: make_case(c.data, CATALOG, RULES) for c in DATASET.cases}


class Scripted:
    def __init__(self, reply: Callable[[Scenario], dict[str, Any]]) -> None:
        self.reply = reply
        self.tasks: set[str] = set()

    async def structured[T: BaseModel](
        self, case_id: str, task: str, schema: type[T], messages: Sequence[BaseMessage]
    ) -> T:
        self.tasks.add(task)
        return schema.model_validate(self.reply(SCENARIOS[case_id]))


def cause(kc_ids: list[str], evidence_ids: list[int]) -> dict[str, Any]:
    return {
        "hypothesis": "scripted",
        "kc_ids": kc_ids,
        "evidence_ids": evidence_ids,
        "confidence": "medium",
        "suggestion": "",
    }


def ideal(s: Scenario) -> dict[str, Any]:
    """Each expected root, citing its target's own mistakes."""
    causes = []
    for root, target in zip(s.case.expect_roots, s.context.neighborhoods, strict=False):
        ids = [m.evidence_id for m in target.target.mistakes]
        causes.append(cause([root[0]], ids))
    return {"root_causes": causes}


def test_the_set_has_patterns_and_quiet_cases_in_both_languages() -> None:
    cases = [s.case for s in SCENARIOS.values()]
    assert len(cases) >= 12
    assert sum(not c.expect_roots for c in cases) >= 3
    assert {c.explain_in for c in cases} == {"zh", "en"}
    assert any(len(c.targets) > 1 for c in cases)
    assert set(DATASET.thresholds) == {"root_found", "no_cause_without_pattern", "citations_hold"}


def test_neighborhoods_are_built_from_the_catalog_as_in_the_app() -> None:
    s = SCENARIOS["past-perfect-behind-third-conditional"]
    [n] = s.context.neighborhoods
    chain = [(p.kc.id, p.depth) for p in n.prerequisites]
    assert chain[:2] == [("g.past_perfect", 1), ("g.second_conditional", 1)]
    assert all(d <= RULES.graph.prerequisite_depth for _, d in chain)
    assert [c.kc.id for c in n.confusables] == ["g.modal_perfect"]
    assert n.target.mistakes[0].evidence_id == 101
    assert s.context.evidence[104] == "g.past_perfect"
    past_perfect = n.prerequisites[0]
    assert past_perfect.required_by == ("g.third_conditional",)
    assert past_perfect.state == "weak"


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"targets": ["g.nope"], "mistakes": {}, "expect_roots": []}, "unknown"),
        (
            {"targets": ["g.prepositions_time"], "mistakes": {}, "expect_roots": [["g.used_to"]]},
            "not shown",
        ),
        (
            {
                "targets": ["g.prepositions_time"],
                "mistakes": {"g.prepositions_time": [{"original": "a", "correction": "b"}] * 4},
                "expect_roots": [],
            },
            "shows",
        ),
    ],
)
def test_bad_cases_are_refused(data: dict[str, Any], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        make_case(data, CATALOG, RULES)


async def test_an_ideal_diagnoser_meets_every_threshold() -> None:
    model = Scripted(ideal)
    report = await evaluate(DiagnosisEval(), model)
    assert report.met, report.render()
    assert model.tasks == {TASK}


async def test_made_up_citations_and_invented_causes_are_caught() -> None:
    def careless(s: Scenario) -> dict[str, Any]:
        return {"root_causes": [cause([s.context.targets[0]], [999, 998])]}

    report = await evaluate(DiagnosisEval(), Scripted(careless))
    assert not report.met
    # Nothing survives the checks, so the quiet cases still pass.
    rendered = report.render()
    assert "citations_hold" in rendered and "root_found" in rendered
