"""The `writing_review` call: what the model returns and how code checks it.

The model sees the text as numbered sentences and reviews only those that need a
change; code keeps a mistake only when its KC is in the catalog and its wrong part
is really in that sentence, so evidence is never written from text the learner did
not write. The four scores are shown to the learner only (P2 plan §4.2).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.adaptive.exercise.inputs import ExplainIn
from app.adaptive.kc.catalog import ErrorType, GrammarCatalog, get_grammar_catalog
from app.adaptive.rules import Severity
from app.memory.reflection import render_catalog
from app.prompts import load_prompt
from app.writing.text import Sentence

TASK = "writing_review"

_LANGUAGES = {"zh": "Simplified Chinese", "en": "English"}
# A dictionary-form English word, as reflection takes them for the word list.
_SINGLE_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)?")
MAX_VOCAB = 5

ScoreName = Literal["task", "coherence", "vocabulary", "grammar"]
SCORE_NAMES: tuple[ScoreName, ...] = ("task", "coherence", "vocabulary", "grammar")


class Mistake(BaseModel):
    kc_id: str = Field(description="Grammar KC id from the catalog")
    error_type: ErrorType
    severity: Severity
    original: str = Field(description="The smallest wrong part of the sentence, exact")
    correction: str = Field(description="That part corrected")
    explanation: str = Field(description="One short sentence to the learner on why")


class SentenceReview(BaseModel):
    index: int = Field(description="The number of the sentence, as given")
    corrected: str = Field(description="The whole sentence with every mistake fixed")
    mistakes: list[Mistake] = Field(default_factory=list)


class Score(BaseModel):
    score: int = Field(ge=1, le=5, description="1 (very weak) to 5 (very good) for the level")
    reason: str = Field(description="One short sentence on why")


class Scores(BaseModel):
    task: Score = Field(description="Does the text do what the task asks, fully")
    coherence: Score = Field(description="Organisation, linking and flow of ideas")
    vocabulary: Score = Field(description="Range and accuracy of words")
    grammar: Score = Field(description="Range and accuracy of grammar")


class Review(BaseModel):
    sentences: list[SentenceReview] = Field(
        default_factory=list, description="Only the sentences that need a change"
    )
    scores: Scores
    summary: str = Field(description="Two or three sentences of overall feedback")
    vocab_candidates: list[str] = Field(
        default_factory=list,
        description="English words the learner clearly did not know (wrote around them, "
        "in another language or badly misspelled), in dictionary form",
    )


@cache
def system_prompt() -> str:
    """Instructions plus the catalog: the same on every call, so vendors can cache it."""
    catalog = render_catalog(get_grammar_catalog())
    return f"{load_prompt(TASK)}\n\n## Grammar catalog\n\n{catalog}"


def review_messages(
    prompt: str, parts: Sequence[Sentence], level: str, explain_in: ExplainIn
) -> list[BaseMessage]:
    numbered = "\n".join(f"[{s.index}] {s.text}" for s in parts)
    lines = [
        f"Learner's level (CEFR): {level}",
        f"Write explanations, reasons and the summary in: {_LANGUAGES[explain_in]}",
        f"Task: {prompt}" if prompt.strip() else "Task: none given (the learner chose freely)",
        f"The learner's text, one numbered sentence per line:\n{numbered}",
    ]
    return [SystemMessage(system_prompt()), HumanMessage("\n\n".join(lines))]


@dataclass(frozen=True, slots=True)
class Checked:
    """A review with only what code could verify."""

    # Per sentence of the text, in order: original, corrected (None when unchanged)
    # and the mistakes kept, as stored in `writing_submissions.corrections`.
    corrections: list[dict[str, object]]
    scores: dict[str, dict[str, object]]
    summary: str
    vocab: list[str]
    # How many mistakes the model gave that code dropped, for the logs.
    dropped: int


def check(review: Review, parts: Sequence[Sentence], catalog: GrammarCatalog) -> Checked:
    by_index: dict[int, SentenceReview] = {}
    for reviewed in review.sentences:
        by_index.setdefault(reviewed.index, reviewed)  # the first wins when one repeats
    dropped = sum(len(r.mistakes) for i, r in by_index.items() if not 0 <= i < len(parts))
    corrections: list[dict[str, object]] = []
    for sentence in parts:
        item = by_index.get(sentence.index)
        kept: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for m in item.mistakes if item else []:
            wrong = m.original.strip()
            key = (m.kc_id, wrong.casefold())
            if m.kc_id not in catalog or not wrong or wrong not in sentence.text or key in seen:
                dropped += 1
                continue
            seen.add(key)
            kept.append(m.model_dump(mode="json") | {"original": wrong})
        corrected = (item.corrected.strip() if item else "") or None
        if corrected == sentence.text:
            corrected = None
        corrections.append(
            {
                "index": sentence.index,
                "paragraph": sentence.paragraph,
                "original": sentence.text,
                "corrected": corrected,
                "mistakes": kept,
            }
        )
    vocab: list[str] = []
    for word in review.vocab_candidates:
        word = word.strip()
        if _SINGLE_WORD.fullmatch(word) and word.casefold() not in {v.casefold() for v in vocab}:
            vocab.append(word)
    return Checked(
        corrections=corrections,
        scores={name: getattr(review.scores, name).model_dump() for name in SCORE_NAMES},
        summary=review.summary.strip(),
        vocab=vocab[:MAX_VOCAB],
        dropped=dropped,
    )


__all__: Sequence[str] = ("TASK", "Checked", "Review", "check", "review_messages")
