"""The `diagnose` call and the code checks on what it returns (Q46c).

The model may only cite KCs and mistakes it was shown; a cause keeps the citations
that hold and is dropped below `diagnosis.min_evidence` of them. Its confidence is
kept for display, never used in a number (Q46e).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.adaptive.diagnosis.context import DiagnosisContext, Language, render
from app.adaptive.rules import Rules
from app.agents.exercise_graph import StructuredCall
from app.prompts import load_prompt

TASK = "diagnose"

type Confidence = Literal["low", "medium", "high"]


class RootCauseOut(BaseModel):
    hypothesis: str = Field(description="What goes wrong and why, to the learner")
    kc_ids: list[str] = Field(description="KC ids the cause lies in, root first")
    evidence_ids: list[int] = Field(description="Evidence numbers of the mistakes showing it")
    confidence: Confidence
    suggestion: str = Field(description="One concrete thing to practise")


class DiagnosisOut(BaseModel):
    root_causes: list[RootCauseOut] = Field(description="At most three, most likely first")


@dataclass(frozen=True, slots=True)
class RootCause:
    hypothesis: str
    kc_ids: tuple[str, ...]
    evidence_ids: tuple[int, ...]
    confidence: Confidence
    suggestion: str

    def as_json(self) -> dict[str, Any]:
        return {
            "hypothesis": self.hypothesis,
            "kc_ids": list(self.kc_ids),
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "suggestion": self.suggestion,
        }


def check(output: DiagnosisOut, context: DiagnosisContext, rules: Rules) -> list[RootCause]:
    """The causes that hold up, in the model's order, at most `max_hypotheses`."""
    diagnosis = rules.diagnosis
    kept: list[RootCause] = []
    for cause in output.root_causes:
        hypothesis = cause.hypothesis.strip()
        kc_ids = _unique(k for k in cause.kc_ids if k in context.kc_ids)
        if not hypothesis or not kc_ids:
            continue
        evidence = _unique(e for e in cause.evidence_ids if context.supports(e, kc_ids))
        if len(evidence) < diagnosis.min_evidence:
            continue
        kept.append(
            RootCause(
                hypothesis=hypothesis,
                kc_ids=kc_ids,
                evidence_ids=evidence,
                confidence=cause.confidence,
                suggestion=cause.suggestion.strip(),
            )
        )
        if len(kept) == diagnosis.max_hypotheses:
            break
    return kept


def _unique[T](items: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


async def diagnose(
    call: StructuredCall, context: DiagnosisContext, language: Language, rules: Rules
) -> tuple[list[RootCause], str | None]:
    """The checked causes and the model that answered (raises the provider's error)."""
    messages = [SystemMessage(load_prompt(TASK)), HumanMessage(render(context, language))]
    reply = await call(messages, DiagnosisOut)
    return check(cast(DiagnosisOut, reply.output), context, rules), reply.model
