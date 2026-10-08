"""What the rewrite, question and critic calls return, and the checks code makes on it
(Q42b, Q42d).

The model writes each question as its right answer and three distractors; code shuffles
them into four options, so the answer's place carries no pattern. A question is kept
only if its evidence sentence is really in the rewrite and its options differ; the
critic then answers it without the key.
"""

import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.adaptive.rules import WordRange
from app.services.news.clean import count_words

OPTIONS = 4


class QuestionDraft(BaseModel):
    position: int = Field(description="The question's position, from 1")
    question: str = Field(description="The question, in English")
    correct: str = Field(description="The right answer")
    distractors: list[str] = Field(description="Three wrong answers")
    evidence: str = Field(
        description="The sentence of your rewrite that gives the answer, copied exactly"
    )


class ArticleRewrite(BaseModel):
    title: str = Field(description="The title, rewritten for the level")
    paragraphs: list[str] = Field(description="The rewritten article, one string per paragraph")
    questions: list[QuestionDraft] = Field(description="Comprehension questions")


class QuestionSet(BaseModel):
    questions: list[QuestionDraft] = Field(description="One new question per position asked")


class QuestionReview(BaseModel):
    position: int = Field(description="The question's position, echoed")
    own_answer: int = Field(description="Your answer: the option's index, 0 to 3")
    answer_in_text: bool = Field(description="The text states or clearly implies the answer")
    one_answer: bool = Field(description="Exactly one option is right")
    needs_text: bool = Field(description="It cannot be answered from general knowledge alone")
    content_ok: bool = Field(description="Clear, natural English at the level")
    problems: list[str] = Field(description="What is wrong, one short sentence each")


class QuestionReviews(BaseModel):
    reviews: list[QuestionReview]


@dataclass(frozen=True, slots=True)
class Question:
    position: int
    question: str
    options: tuple[str, ...]
    answer: int
    evidence: str

    def stored(self) -> dict[str, Any]:
        """As saved in `article_versions.questions`."""
        return {
            "question": self.question,
            "options": list(self.options),
            "answer": self.answer,
            "evidence": self.evidence,
        }

    def shown(self) -> dict[str, Any]:
        """What the critic sees: no answer key, no evidence."""
        return {"position": self.position, "question": self.question, "options": self.options}


class DraftError(ValueError):
    pass


_SPACE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text.replace("\u2019", "'")).strip().lower()


def clean_paragraphs(paragraphs: Sequence[str]) -> list[str]:
    return [p for p in (_SPACE.sub(" ", p).strip() for p in paragraphs) if p]


def text_problem(paragraphs: Sequence[str], words: WordRange, slack: float) -> str | None:
    """Why the rewrite cannot be used, or None."""
    if not paragraphs:
        return "the rewrite is empty"
    total = count_words("\n\n".join(paragraphs))
    low, high = round(words.min * (1 - slack)), round(words.max * (1 + slack))
    if not low <= total <= high:
        return (
            f"the rewrite has {total} words; it must have {words.min} to {words.max} "
            f"(and never fewer than {low} or more than {high})"
        )
    return None


def to_question(draft: QuestionDraft, paragraphs: Sequence[str], rng: random.Random) -> Question:
    """Check a draft against the rewrite and shuffle its options; `DraftError` says why
    it cannot be used."""
    question, correct = draft.question.strip(), draft.correct.strip()
    distractors = [d.strip() for d in draft.distractors]
    if not question or not correct:
        raise DraftError("the question or its answer is empty")
    if len(distractors) != OPTIONS - 1 or not all(distractors):
        raise DraftError(f"needs exactly {OPTIONS - 1} non-empty distractors")
    if len({_norm(o) for o in [correct, *distractors]}) != OPTIONS:
        raise DraftError("two options are the same")
    evidence = draft.evidence.strip()
    if not evidence or _norm(evidence) not in _norm(" ".join(paragraphs)):
        raise DraftError("the evidence is not a sentence copied from the rewrite")
    options = [correct, *distractors]
    rng.shuffle(options)
    return Question(draft.position, question, tuple(options), options.index(correct), evidence)


def rejection(question: Question, review: QuestionReview) -> list[str]:
    """Why the critic's review rejects the question; empty when it passes. A problem
    the critic notes on a question it otherwise passes does not reject it."""
    failed = [
        name
        for name, ok in (
            ("the answer is not in the text", review.answer_in_text),
            ("more than one option could be right", review.one_answer),
            ("it can be answered without reading", review.needs_text),
            ("the wording is unclear or unnatural", review.content_ok),
        )
        if not ok
    ]
    if review.own_answer != question.answer:
        failed.append("a careful reader picked a different option")
    return [*failed, *(p.strip() for p in review.problems if p.strip())] if failed else []
