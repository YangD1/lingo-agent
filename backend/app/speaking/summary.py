"""The summary of a speaking session (ADR 0029 §5).

One `speaking_summary` structured call over the conversation; code then keeps only
what it can check: a mistake or a more natural way of saying something must quote the
learner's own words. The summary is shown, never recorded as evidence (reflection
already did that); its intelligibility rating moves speaking ability in code (Q58d).
"""

import re
from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import Intelligibility
from app.prompts import load_prompt
from app.speaking.scenarios import Scenario

TASK = "speaking_summary"
# The conversation the model reads: the latest turns when it ran long.
MAX_TRANSCRIPT_CHARS = 12000

type ExplainIn = Literal["zh", "en"]


class Mistake(BaseModel):
    quote: str = Field(description="The learner's words, copied exactly from one turn.")
    correction: str = Field(description="The corrected sentence or phrase, in English.")
    explanation: str = Field(description="Why, in one short sentence, in the asked language.")


class Natural(BaseModel):
    quote: str = Field(description="The learner's words, copied exactly from one turn.")
    natural: str = Field(description="How a fluent speaker would more likely say it.")
    note: str = Field(description="What makes it more natural, briefly, in the asked language.")


class Expression(BaseModel):
    expression: str = Field(description="An English expression worth practising next time.")
    meaning: str = Field(description="What it means or when to use it, in the asked language.")


class SpeakingSummary(BaseModel):
    """The `speaking_summary` task's answer."""

    went_well: list[str] = Field(
        description="Up to 3 things the learner did well, in the asked language.", max_length=3
    )
    mistakes: list[Mistake] = Field(
        description="Up to 6 mistakes worth going through, the ones that matter most first.",
        max_length=6,
    )
    more_natural: list[Natural] = Field(
        description="Up to 4 correct but unnatural phrasings, with a more natural version.",
        max_length=4,
    )
    next_expressions: list[Expression] = Field(
        description="Up to 4 expressions for this situation the learner could try next time.",
        max_length=4,
    )
    intelligibility: Intelligibility = Field(
        description="How easily a listener would understand the learner overall: hard, "
        "partly, mostly or fully."
    )


def summary_messages(
    messages: Sequence[BaseMessage],
    *,
    scenario: Scenario | None,
    level: CefrLevel,
    explain_in: ExplainIn,
) -> list[BaseMessage]:
    situation = (
        f"{scenario.title_en}. The learner's goal: {scenario.learner_goal_en}"
        if scenario
        else "Free talk."
    )
    lines = []
    for message in messages:
        speaker = "Learner" if isinstance(message, HumanMessage) else "Partner"
        lines.append(f"{speaker}: {message.text.strip()}")
    transcript = "\n".join(lines)[-MAX_TRANSCRIPT_CHARS:]
    prompt = (
        load_prompt(TASK)
        .replace("{language}", "Simplified Chinese" if explain_in == "zh" else "English")
        .replace("{level}", level)
    )
    return [
        SystemMessage(prompt),
        HumanMessage(
            f"## Situation\n{situation}\n\n## Conversation (transcribed speech)\n"
            f"<conversation>\n{transcript}\n</conversation>"
        ),
    ]


def check(summary: SpeakingSummary, learner_texts: Sequence[str]) -> dict[str, Any]:
    """The summary to store: quotes not found in the learner's turns are dropped, and
    empty strings left out."""
    # Padded so a quote matches whole words only ("he" is not in "she").
    said = [f" {_normal(text)} " for text in learner_texts]

    def quoted(quote: str) -> bool:
        needle = _normal(quote)
        return bool(needle) and any(f" {needle} " in text for text in said)

    return {
        "went_well": [w.strip() for w in summary.went_well if w.strip()],
        "mistakes": [
            m.model_dump() for m in summary.mistakes if quoted(m.quote) and m.correction.strip()
        ],
        "more_natural": [
            n.model_dump() for n in summary.more_natural if quoted(n.quote) and n.natural.strip()
        ],
        "next_expressions": [e.model_dump() for e in summary.next_expressions if e.expression],
        "intelligibility": summary.intelligibility,
    }


def _normal(text: str) -> str:
    """Lower case, words and apostrophes only, single spaces: a quote may differ from
    the turn in case, punctuation or spacing."""
    return " ".join(re.sub(r"[^\w']+", " ", text.lower()).split())
