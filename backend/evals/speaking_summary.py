"""The speaking summary evaluator (task 64.3, Q64w): `summary_messages` -> the model ->
`check`, as a session's summary is made and stored.

Each case is a spoken conversation as the learner's turns were transcribed: a cascade
session (push to talk, whole sentences) or a realtime call (cut where the learner
paused). Metrics, on what `check` keeps: `real_mistakes_found` (each expected mistake is
quoted by a kept mistake) and `transcript_left_alone` (nothing kept quotes a stretch
that is only a transcription artefact: a fragment of a sentence split at a pause, or
punctuation the learner couldn't have said).
"""

from typing import Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field

from app.adaptive.kc.catalog import CefrLevel
from app.speaking.scenarios import get_scenarios
from app.speaking.summary import TASK, SpeakingSummary, _normal, check, summary_messages
from evals.dataset import Case
from evals.models import EvalModel
from evals.report import CaseResult


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    learner: str | None = None
    partner: str | None = None


class SummaryCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["cascade", "realtime"]
    scenario: str | None = None
    level: str = "B1"
    explain_in: Literal["zh", "en"] = "zh"
    turns: list[Turn] = Field(min_length=2)
    # Words of a real mistake: some kept mistake must quote them.
    expect_mistakes: list[str] = []
    # How a turn that only looks wrong because of transcription begins (a sentence cut
    # at a pause, "Like playing football."): no kept mistake or more natural version may
    # quote from there.
    artefacts: list[str] = []


def _messages(case: SummaryCase) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for turn in case.turns:
        if (turn.learner is None) == (turn.partner is None):
            raise ValueError("a turn is either the learner's or the partner's")
        out.append(HumanMessage(turn.learner) if turn.learner else AIMessage(turn.partner or ""))
    return out


def _has(quote: str, words: str) -> bool:
    return f" {_normal(words)} " in f" {_normal(quote)} "


def _starts(quote: str, words: str) -> bool:
    return f"{_normal(quote)} ".startswith(f"{_normal(words)} ")


class SpeakingSummaryEval:
    name = "speaking_summary"

    async def run_case(self, case: Case, model: EvalModel) -> CaseResult:
        c = SummaryCase.model_validate(case.data)
        scenario = get_scenarios().get(c.scenario) if c.scenario else None
        if c.scenario and scenario is None:
            raise ValueError(f"unknown scenario {c.scenario!r}")
        messages = _messages(c)
        out = await model.structured(
            case.id,
            TASK,
            SpeakingSummary,
            summary_messages(
                messages,
                scenario=scenario,
                level=cast(CefrLevel, c.level),
                explain_in=c.explain_in,
                call=c.mode == "realtime",
            ),
        )
        kept = check(
            out,
            [m.text for m in messages if isinstance(m, HumanMessage)],
            call=c.mode == "realtime",
        )
        mistakes = [m["quote"] for m in kept["mistakes"]]
        quoted = mistakes + [n["quote"] for n in kept["more_natural"]]
        checks: dict[str, bool] = {}
        if c.expect_mistakes:
            checks["real_mistakes_found"] = all(
                any(_has(q, words) for q in mistakes) for words in c.expect_mistakes
            )
        if c.artefacts:
            checks["transcript_left_alone"] = not any(
                _starts(q, words) for q in quoted for words in c.artefacts
            )
        detail = "\n".join(
            [f"mistake: {m['quote']} -> {m['correction']}" for m in kept["mistakes"]]
            + [f"natural: {n['quote']} -> {n['natural']}" for n in kept["more_natural"]]
        )
        return CaseResult(case.id, checks, detail)
