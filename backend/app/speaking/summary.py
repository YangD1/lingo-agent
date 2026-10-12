"""The summary of a speaking session (ADR 0029 §5).

One `speaking_summary` structured call over the conversation; code then keeps only
what it can check: a mistake or a more natural way of saying something must quote the
learner's own words and change more than punctuation or case (task 64.2: the model
"corrected" quotation marks in speech). The summary is shown, never recorded as
evidence (reflection already did that); its intelligibility rating moves speaking
ability in code (Q58d).
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
    call: bool = False,
) -> list[BaseMessage]:
    """`call`: a realtime call, whose transcripts break at the learner's pauses (Q64w)."""
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
    if call:
        prompt = f"{prompt}\n\n{load_prompt(f'{TASK}_call')}"
    return [
        SystemMessage(prompt),
        HumanMessage(
            f"## Situation\n{situation}\n\n## Conversation (transcribed speech)\n"
            f"<conversation>\n{transcript}\n</conversation>"
        ),
    ]


def check(
    summary: SpeakingSummary, learner_texts: Sequence[str], *, call: bool = False
) -> dict[str, Any]:
    """The summary to store: quotes not found in the learner's turns are dropped, and
    empty strings left out. In a call, so is a "fix" that only adds words in front of a
    turn's start or after its end: that mends where recognition cut, not the learner
    (Q64w)."""
    # Padded so a quote matches whole words only ("he" is not in "she").
    said = [f" {_normal(text)} " for text in learner_texts]

    def quoted(quote: str) -> bool:
        needle = _normal(quote)
        return bool(needle) and any(f" {needle} " in text for text in said)

    turns = [_bare(text) for text in learner_texts]

    def changed(quote: str, better: str) -> bool:
        q, b = _bare(quote), _bare(better)
        if not b or b == q:
            return False
        if call and q:
            starts = any(t == q or t.startswith(f"{q} ") for t in turns)
            ends = any(t == q or t.endswith(f" {q}") for t in turns)
            if (starts and b.endswith(f" {q}")) or (ends and b.startswith(f"{q} ")):
                return False
        return True

    return {
        "went_well": [w.strip() for w in summary.went_well if w.strip()],
        "mistakes": [
            m.model_dump()
            for m in summary.mistakes
            if quoted(m.quote) and changed(m.quote, m.correction)
        ],
        "more_natural": [
            n.model_dump()
            for n in summary.more_natural
            if quoted(n.quote) and changed(n.quote, n.natural)
        ],
        "next_expressions": [e.model_dump() for e in summary.next_expressions if e.expression],
        "intelligibility": summary.intelligibility,
    }


def _normal(text: str) -> str:
    """Lower case, words and apostrophes only, single spaces: a quote may differ from
    the turn in case, punctuation or spacing."""
    return " ".join(re.sub(r"[^\w']+", " ", text.lower()).split())


def _bare(text: str) -> str:
    """`_normal`, and single quotes around a word dropped too ('serendipity'); an
    apostrophe inside one stays (it's / its)."""
    return " ".join(word.strip("'") for word in _normal(text).split())
