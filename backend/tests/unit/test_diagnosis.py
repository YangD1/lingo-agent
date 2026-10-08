"""Diagnosis targets, the context shown to the model and the checks on its causes
(task 46.2, Q46a / Q46c)."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from app.adaptive.diagnosis.checks import DiagnosisOut, RootCauseOut, check, diagnose
from app.adaptive.diagnosis.context import DiagnosisContext, pick_targets, render
from app.adaptive.graph import GraphNode, Mistake, Neighborhood, Relation
from app.adaptive.kc.catalog import GrammarKC
from app.adaptive.rules import get_rules
from app.agents.exercise_graph import ModelReply

RULES = get_rules()  # min_mistakes 3, max_kcs 3, min_evidence 2, max_hypotheses 3
T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _kc(kc_id: str, **fields: Any) -> GrammarKC:
    base = {"id": kc_id, "name_en": kc_id, "name_zh": kc_id, "cefr": "B1"}
    return GrammarKC.model_validate(base | {"description": f"Uses {kc_id}."} | fields)


def _node(kc_id: str, relation: Relation, evidence: Sequence[int] = (), **fields: Any) -> GraphNode:
    return GraphNode(
        kc=_kc(kc_id, **fields),
        relation=relation,
        depth=0 if relation == "target" else 1,
        required_by=("g.t",) if relation == "prerequisite" else (),
        mastery=None,
        state=None,
        mistakes=tuple(
            Mistake(e, "chat", "wrong_form", "medium", f"wrong {e}", f"right {e}", T0)
            for e in evidence
        ),
    )


# g.t's mistakes are 1-3, its prerequisite g.p's 4, its confusable g.c's 5; g.u, a
# second target, has 6-7 and no neighbors.
CONTEXT = DiagnosisContext(
    (
        Neighborhood(
            target=_node("g.t", "target", [1, 2, 3], common_errors=("drops -ed",)),
            prerequisites=[_node("g.p", "prerequisite", [4])],
            confusables=[_node("g.c", "confusable", [5])],
        ),
        Neighborhood(target=_node("g.u", "target", [6, 7]), prerequisites=[], confusables=[]),
    )
)


def _cause(kc_ids: list[str], evidence_ids: list[int], **fields: Any) -> RootCauseOut:
    base = {
        "hypothesis": "You drop the participle.",
        "confidence": "medium",
        "suggestion": "Practise past participles.",
    }
    return RootCauseOut.model_validate(
        base | {"kc_ids": kc_ids, "evidence_ids": evidence_ids} | fields
    )


def test_targets_are_weak_kcs_with_enough_mistakes_in_priority_order() -> None:
    weak = ["g.a", "g.b", "g.c", "g.d", "g.e"]
    mistakes = {"g.a": 2, "g.b": 3, "g.c": 5, "g.d": 3, "g.e": 9, "g.learned": 9}
    assert pick_targets(weak, mistakes, RULES) == ["g.b", "g.c", "g.d"]
    assert pick_targets(weak, {"g.a": 2}, RULES) == []


def test_context_knows_shown_kcs_and_evidence() -> None:
    assert CONTEXT.targets == ["g.t", "g.u"]
    assert CONTEXT.kc_ids == {"g.t", "g.p", "g.c", "g.u"}
    assert CONTEXT.evidence == {
        1: "g.t",
        2: "g.t",
        3: "g.t",
        4: "g.p",
        5: "g.c",
        6: "g.u",
        7: "g.u",
    }


def test_render_lists_each_target_with_its_neighbors_and_numbered_mistakes() -> None:
    text = render(CONTEXT, "zh")
    assert text.startswith("Write in: Simplified Chinese")
    assert "## Grammar point 1: g.t" in text and "## Grammar point 2: g.u" in text
    assert "Typical errors: drops -ed" in text
    assert "1 step(s) up, needed by g.t" in text
    assert '- evidence 4 (chat, wrong_form, medium): "wrong 4" -> "right 4"' in text
    assert "no evidence yet" in text
    assert render(CONTEXT, "en").startswith("Write in: English")


def test_a_cause_in_a_prerequisite_may_cite_the_targets_mistakes() -> None:
    kept = check(DiagnosisOut(root_causes=[_cause(["g.p"], [1, 2, 4])]), CONTEXT, RULES)
    assert [(c.kc_ids, c.evidence_ids) for c in kept] == [(("g.p",), (1, 2, 4))]
    assert kept[0].as_json() == {
        "hypothesis": "You drop the participle.",
        "kc_ids": ["g.p"],
        "evidence_ids": [1, 2, 4],
        "confidence": "medium",
        "suggestion": "Practise past participles.",
    }


@pytest.mark.parametrize(
    ("cause", "kept"),
    [
        # Made-up and another neighborhood's evidence are dropped: one valid left.
        (_cause(["g.t"], [1, 99, 6]), None),
        # Repeated citations count once.
        (_cause(["g.t"], [1, 1]), None),
        # KCs not shown are dropped; the cause stays on those that were.
        (_cause(["g.nope", "g.t"], [1, 2]), (("g.t",), (1, 2))),
        # Nothing left to lie in.
        (_cause(["g.nope"], [1, 2]), None),
        (_cause(["g.t"], [1, 2], hypothesis="  "), None),
        # g.u's own mistakes back a cause in g.u.
        (_cause(["g.u"], [6, 7, 7]), (("g.u",), (6, 7))),
    ],
)
def test_citations_that_do_not_hold_are_dropped(
    cause: RootCauseOut, kept: tuple[tuple[str, ...], tuple[int, ...]] | None
) -> None:
    found = check(DiagnosisOut(root_causes=[cause]), CONTEXT, RULES)
    assert [(c.kc_ids, c.evidence_ids) for c in found] == ([kept] if kept else [])


def test_at_most_max_hypotheses_are_kept_in_order() -> None:
    causes = [_cause(["g.t"], [1, 2], hypothesis=f"Cause {n}.") for n in range(5)]
    kept = check(DiagnosisOut(root_causes=causes), CONTEXT, RULES)
    assert [c.hypothesis for c in kept] == ["Cause 0.", "Cause 1.", "Cause 2."]


async def test_diagnose_sends_the_context_and_checks_the_reply() -> None:
    sent: list[Any] = []

    async def call(messages: Sequence[Any], schema: type[Any]) -> ModelReply:
        sent.append((messages, schema))
        reply = DiagnosisOut(root_causes=[_cause(["g.t"], [1, 2]), _cause(["g.t"], [99])])
        return ModelReply(reply, "conn:model")

    causes, model = await diagnose(call, CONTEXT, "en", RULES)

    assert model == "conn:model"
    assert [c.evidence_ids for c in causes] == [(1, 2)]
    messages, schema = sent[0]
    assert schema is DiagnosisOut
    assert "root causes" in messages[0].content
    assert messages[1].content == render(CONTEXT, "en")
