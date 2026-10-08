"""The messages of the `article_rewrite`, `reading_questions` and `reading_critic` calls.

The system prompts live in `app/prompts/`; this module writes the per-article part.
Questions are introduced by their position, which the models echo back.
"""

import json
from collections.abc import Mapping, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.adaptive.rules import WordRange
from app.prompts import load_prompt
from app.services.news.clean import count_words
from app.services.reading.drafts import Question


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def source_paragraphs(body: str, max_words: int) -> list[str]:
    """The article's paragraphs up to `max_words` words, cut at a paragraph boundary
    (always at least the first one) (Q42b)."""
    kept: list[str] = []
    total = 0
    for paragraph in (p.strip() for p in body.split("\n\n")):
        if not paragraph:
            continue
        words = count_words(paragraph)
        if kept and total + words > max_words:
            break
        kept.append(paragraph)
        total += words
    return kept


def _text(title: str, paragraphs: Sequence[str]) -> str:
    return f"# {title}\n\n" + "\n\n".join(paragraphs)


def rewrite_messages(
    title: str,
    source: Sequence[str],
    *,
    level: str,
    words: WordRange,
    questions: int,
    problem: str | None = None,
) -> list[BaseMessage]:
    parts = [
        f"Learner's level (CEFR): {level}",
        f"Length of the rewrite: {words.min} to {words.max} words",
        f"Questions to write: {questions}",
        "The article:\n\n" + _text(title, source),
    ]
    if problem:
        parts.append(f"Your last attempt was rejected: {problem}. Write it again.")
    return [SystemMessage(load_prompt("article_rewrite")), HumanMessage("\n\n".join(parts))]


def questions_messages(
    title: str,
    paragraphs: Sequence[str],
    *,
    level: str,
    kept: Sequence[Question],
    rejected: Mapping[int, tuple[Mapping[str, object], Sequence[str]]],
) -> list[BaseMessage]:
    """Ask for new questions at the `rejected` positions: {position: (draft, reasons)}."""
    parts = [
        f"Learner's level (CEFR): {level}",
        "The text:\n\n" + _text(title, paragraphs),
        "Questions kept (do not repeat them):\n" + _json([q.question for q in kept]),
        "Rejected questions; write a new one for each position:\n"
        + _json(
            [
                {"position": p, "rejected_question": draft, "problems": list(reasons)}
                for p, (draft, reasons) in sorted(rejected.items())
            ]
        ),
    ]
    return [SystemMessage(load_prompt("reading_questions")), HumanMessage("\n\n".join(parts))]


def critic_messages(
    title: str, paragraphs: Sequence[str], *, level: str, questions: Sequence[Question]
) -> list[BaseMessage]:
    parts = [
        f"Learner's level (CEFR): {level}",
        "The text:\n\n" + _text(title, paragraphs),
        "Questions to review:\n" + _json([q.shown() for q in questions]),
    ]
    return [SystemMessage(load_prompt("reading_critic")), HumanMessage("\n\n".join(parts))]
