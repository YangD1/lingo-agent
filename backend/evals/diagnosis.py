"""The diagnosis evaluator (task 46.6, Q46g): `diagnose_messages` -> `diagnose` -> `check`.

Each case is a learner's mistakes on up to three target KCs and their neighbors. The
neighborhoods are built from the catalog as `graph.neighborhood` builds them from
`kc_edges` (prerequisites by shortest distance up to `graph.prerequisite_depth`, then
confusables not already in the chain), so no database is needed.

Metrics: `root_found` (cases with a real pattern: each expected root is named by a
cause that survives the checks), `no_cause_without_pattern` (cases without one: no
cause survives) and `citations_hold` (every case: the model cited only KCs and
mistakes it was shown, in a way the checks accept, before any were dropped).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.adaptive.diagnosis.checks import TASK, DiagnosisOut, check, diagnose_messages
from app.adaptive.diagnosis.context import DiagnosisContext, Language
from app.adaptive.graph import GraphNode, Mistake, Neighborhood, Relation
from app.adaptive.kc.catalog import ErrorType, GrammarCatalog, get_grammar_catalog
from app.adaptive.learner import mastery_state
from app.adaptive.rules import Rules, get_rules
from app.db.models import KCMastery
from evals.dataset import Case
from evals.models import EvalModel
from evals.report import CaseResult

# Mistakes are numbered from here, in the order the case lists them.
FIRST_EVIDENCE_ID = 101
_WHEN = datetime(2026, 10, 1, tzinfo=UTC)


class MistakeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original: str
    correction: str
    error_type: ErrorType = "wrong_form"
    severity: Literal["low", "medium", "high"] = "medium"
    source: Literal["chat", "exercise", "writing"] = "chat"


class DiagnosisCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    targets: list[str] = Field(min_length=1, max_length=3)
    # By KC id, newest first, as the neighborhood shows them.
    mistakes: dict[str, list[MistakeSpec]]
    # p_mastery by KC; KCs left out have no evidence yet.
    mastery: dict[str, float] = {}
    # Each entry is one root the diagnosis should find, as acceptable KC ids; empty
    # when the mistakes show no pattern and no cause should survive.
    expect_roots: list[list[str]]
    explain_in: Language = "zh"


@dataclass(frozen=True, slots=True)
class Scenario:
    case: DiagnosisCase
    context: DiagnosisContext


def _chain(kc_id: str, catalog: GrammarCatalog, depth: int) -> list[tuple[str, int]]:
    seen: dict[str, int] = {}
    frontier = [kc_id]
    for step in range(1, depth + 1):
        found = {
            p
            for k in frontier
            for p in catalog.get(k).prerequisites  # type: ignore[union-attr]
            if p not in seen and p != kc_id
        }
        seen.update(dict.fromkeys(found, step))
        frontier = sorted(found)
    return sorted(seen.items(), key=lambda item: (item[1], item[0]))


def make_case(data: Mapping[str, Any], catalog: GrammarCatalog, rules: Rules) -> Scenario:
    case = DiagnosisCase.model_validate(data)
    known = {kc.id for kc in catalog.kcs}
    named = {
        *case.targets,
        *case.mistakes,
        *case.mastery,
        *(k for root in case.expect_roots for k in root),
    }
    if unknown := named - known:
        raise ValueError(f"unknown grammar KCs {sorted(unknown)}")
    numbered: dict[str, tuple[Mistake, ...]] = {}
    next_id = FIRST_EVIDENCE_ID
    for kc_id, specs in case.mistakes.items():
        if len(specs) > rules.graph.mistakes_per_kc:
            raise ValueError(f"{kc_id}: a neighborhood shows {rules.graph.mistakes_per_kc}")
        numbered[kc_id] = tuple(
            Mistake(
                next_id + n, s.source, s.error_type, s.severity, s.original, s.correction, _WHEN
            )
            for n, s in enumerate(specs)
        )
        next_id += len(specs)

    def node(kc_id: str, relation: Relation, depth: int, requirers: Sequence[str]) -> GraphNode:
        kc = catalog.get(kc_id)
        assert kc is not None
        p = case.mastery.get(kc_id)
        return GraphNode(
            kc=kc,
            relation=relation,
            depth=depth,
            required_by=tuple(
                r
                for r in requirers
                if kc_id in catalog.get(r).prerequisites  # type: ignore[union-attr]
            ),
            mastery=None if p is None else KCMastery(kc_id=kc_id, kind="grammar", p_mastery=p),
            state=None if p is None else mastery_state(p, rules),
            mistakes=numbered.get(kc_id, ()),
        )

    neighborhoods = []
    for target in case.targets:
        chain = _chain(target, catalog, rules.graph.prerequisite_depth)
        requirers = [target, *(k for k, _ in chain)]
        in_chain = {k for k, _ in chain}
        neighborhoods.append(
            Neighborhood(
                target=node(target, "target", 0, ()),
                prerequisites=[node(k, "prerequisite", d, requirers) for k, d in chain],
                confusables=[
                    node(k, "confusable", 1, ())
                    for k in sorted(catalog.confusables(target))
                    if k not in in_chain
                ],
            )
        )
    context = DiagnosisContext(tuple(neighborhoods))
    if unshown := (set(case.mistakes) | set(case.mastery)) - context.kc_ids:
        raise ValueError(f"mistakes or mastery on KCs not shown: {sorted(unshown)}")
    if unshown := {k for root in case.expect_roots for k in root} - context.kc_ids:
        raise ValueError(f"expected roots not shown: {sorted(unshown)}")
    return Scenario(case, context)


class DiagnosisEval:
    name = "diagnosis"

    def __init__(self, catalog: GrammarCatalog | None = None, rules: Rules | None = None) -> None:
        self.catalog = catalog or get_grammar_catalog()
        self.rules = rules or get_rules()

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        s = make_case(case.data, self.catalog, self.rules)
        out = await model.structured(
            case.id, TASK, DiagnosisOut, diagnose_messages(s.context, s.case.explain_in)
        )
        kept = check(out, s.context, self.rules)
        checks = {
            "citations_hold": all(
                set(c.kc_ids) <= s.context.kc_ids
                and all(s.context.supports(e, c.kc_ids) for e in c.evidence_ids)
                for c in out.root_causes
            )
        }
        if s.case.expect_roots:
            named = [set(c.kc_ids) for c in kept]
            checks["root_found"] = all(
                any(ids & set(root) for ids in named) for root in s.case.expect_roots
            )
        else:
            checks["no_cause_without_pattern"] = not kept
        detail = "\n".join(
            f"{c.confidence} {c.kc_ids} {c.evidence_ids}: {c.hypothesis}" for c in out.root_causes
        )
        return CaseResult(case.id, checks, f"kept {len(kept)}/{len(out.root_causes)}\n{detail}")
