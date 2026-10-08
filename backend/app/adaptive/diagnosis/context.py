"""What a diagnosis looks at (Q46a): the KCs it is about and their neighborhoods.

`pick_targets` and `render` are pure; `load_context` reads the learner's side.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise import inputs
from app.adaptive.exercise.planner import candidates
from app.adaptive.graph import GraphNode, Neighborhood, neighborhood
from app.adaptive.kc.catalog import GrammarCatalog
from app.adaptive.rules import Rules

type Language = Literal["zh", "en"]

LANGUAGE_NAMES: Mapping[Language, str] = {"zh": "Simplified Chinese", "en": "English"}


@dataclass(frozen=True)
class DiagnosisContext:
    """The neighborhoods shown to the model, one per target KC, priority order."""

    neighborhoods: tuple[Neighborhood, ...]

    @property
    def targets(self) -> list[str]:
        return [n.target.kc.id for n in self.neighborhoods]

    @cached_property
    def groups(self) -> list[frozenset[str]]:
        """The KC ids of each neighborhood."""
        return [frozenset(node.kc.id for node in _nodes(n)) for n in self.neighborhoods]

    @cached_property
    def kc_ids(self) -> frozenset[str]:
        return frozenset().union(*self.groups)

    @cached_property
    def evidence(self) -> dict[int, str]:
        """Every mistake shown, by evidence id: the KC it was counted under."""
        return {
            mistake.evidence_id: node.kc.id
            for n in self.neighborhoods
            for node in _nodes(n)
            for mistake in node.mistakes
        }

    def supports(self, evidence_id: int, kc_ids: Sequence[str]) -> bool:
        """Whether a shown mistake can back a cause in `kc_ids` (Q46c): it is on one of
        them, or in a neighborhood that has one of them."""
        kc = self.evidence.get(evidence_id)
        if kc is None:
            return False
        return kc in kc_ids or any(kc in g and not g.isdisjoint(kc_ids) for g in self.groups)


def _nodes(n: Neighborhood) -> list[GraphNode]:
    return [n.target, *n.prerequisites, *n.confusables]


def pick_targets(weak: Sequence[str], mistakes: Mapping[str, int], rules: Rules) -> list[str]:
    """KCs not learned yet (`weak`, highest practice priority first) with enough counted
    mistakes lately; at most `diagnosis.max_kcs`."""
    diagnosis = rules.diagnosis
    return [k for k in weak if mistakes.get(k, 0) >= diagnosis.min_mistakes][: diagnosis.max_kcs]


async def load_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime,
) -> DiagnosisContext | None:
    """The learner's targets and their neighborhoods; None when no KC qualifies. May
    rebuild stale mastery rows; the caller commits."""
    learner = await inputs.load(session, user_id, rules=rules, catalog=catalog, now=now)
    ranked = candidates(catalog, learner.states, learner_level=learner.level, now=now, rules=rules)
    since = now - timedelta(days=rules.diagnosis.mistake_days)
    mistakes = await inputs.counted_mistakes(session, user_id, rules=rules, since=since)
    found = [
        n
        for kc_id in pick_targets(ranked.weak, mistakes, rules)
        if (n := await neighborhood(session, user_id, kc_id, rules=rules, catalog=catalog))
    ]
    return DiagnosisContext(tuple(found)) if found else None


def render(context: DiagnosisContext, language: Language) -> str:
    """The user message: each target with its prerequisites and confusables."""
    parts = [f"Write in: {LANGUAGE_NAMES[language]}"]
    for number, n in enumerate(context.neighborhoods, start=1):
        parts.append(f"## Grammar point {number}: {n.target.kc.id}")
        parts.append(_node(n.target, "the KC the mistakes keep coming under"))
        if n.prerequisites:
            parts.append("### Builds on (prerequisite chain)")
            parts.extend(
                _node(node, f"{node.depth} step(s) up, needed by {', '.join(node.required_by)}")
                for node in n.prerequisites
            )
        if n.confusables:
            parts.append("### Often confused with")
            parts.extend(_node(node, "confusable") for node in n.confusables)
    return "\n\n".join(parts)


def _node(node: GraphNode, role: str) -> str:
    kc = node.kc
    if node.mastery is None:
        mastery = "no evidence yet"
    else:
        mastery = f"p_mastery {node.mastery.p_mastery:.2f} ({node.state})"
    lines = [
        f"- {kc.id} [{kc.cefr}] {kc.name_en} ({role}); {mastery}",
        f"  What it is: {kc.description}",
    ]
    if kc.common_errors:
        lines.append(f"  Typical errors: {'; '.join(kc.common_errors)}")
    if node.mistakes:
        lines.append("  Latest mistakes:")
        lines.extend(
            f"  - evidence {m.evidence_id} ({m.source}, {m.error_type or 'unknown'}, "
            f"{m.severity or 'unrated'}): {_quote(m.original)} -> {_quote(m.correction)}"
            for m in node.mistakes
        )
    else:
        lines.append("  Latest mistakes: none")
    return "\n".join(lines)


def _quote(text: str | None) -> str:
    return f'"{text}"' if text else "(not recorded)"
