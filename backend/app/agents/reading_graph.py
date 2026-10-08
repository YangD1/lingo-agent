"""Graded rewrite graph (ADR 0024 §5, P2 plan §5.3):

    START -> rewrite -> (rewrite again once, if the text is unusable) -> critic
          -> (questions -> critic, at most reading.max_regenerations rounds) -> save -> END

`rewrite` writes the text and its questions in one structured call; code checks the
text's length (Q42b) and each question (`drafts.to_question`). `critic` answers the
questions without the key in one call, and `drafts.rejection` decides; rejected
questions go to `questions` with the reasons. Questions still rejected after the last
round are dropped: an article keeps the questions that passed, even none (Q42d). If the
critic call fails, no question is kept, since none was checked.

As with the practice graph, the model calls come in through the context, so tests run
it with fakes; a version is written in one go and needs no checkpointer.
"""

import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import Rules
from app.agents.exercise_graph import StructuredCall
from app.providers.errors import NoModelConfiguredError
from app.services.reading import drafts, messages
from app.services.reading.drafts import Question, QuestionDraft

logger = logging.getLogger(__name__)

REWRITE_NODE: Final = "rewrite"
CRITIC_NODE: Final = "critic"
QUESTIONS_NODE: Final = "questions"
SAVE_NODE: Final = "save"
# Tries at a usable text before the version fails.
REWRITE_ATTEMPTS: Final = 2

type Stage = Literal["rewriting", "reviewing", "fixing"]


@dataclass(frozen=True, slots=True)
class RewriteResult:
    title: str
    paragraphs: list[str]
    # Passed the critic, by position.
    questions: list[Question]
    # As stored in `article_versions.rejected`.
    rejected: list[dict[str, Any]]
    model: str | None
    critic_model: str | None
    # Set when no usable text was written; nothing else is then.
    error_code: str | None = None


@dataclass(frozen=True)
class ReadingContext:
    rewrite: StructuredCall
    questions: StructuredCall
    critique: StructuredCall
    title: str
    # The original's paragraphs, already cut to reading.max_source_words.
    source: Sequence[str]
    level: CefrLevel
    rules: Rules
    seed: int
    save: Callable[[RewriteResult], Awaitable[None]]
    report: Callable[[Stage], Awaitable[None]] | None = None


type Feedback = dict[int, tuple[dict[str, Any], list[str]]]


class ReadingState(TypedDict, total=False):
    attempts: int
    # Why the last text was unusable, sent back with the next attempt.
    problem: str | None
    title: str
    paragraphs: list[str]
    model: str | None
    critic_model: str | None
    # Questions waiting for the critic, by position.
    pending: dict[int, Question]
    accepted: dict[int, Question]
    # Positions still open, with the last rejected draft and why.
    feedback: Feedback
    rejected: list[dict[str, Any]]
    rounds: int
    # reading.max_regenerations.
    max_rounds: int
    error_code: str | None


type ReadingGraph = CompiledStateGraph[ReadingState, ReadingContext, ReadingState, ReadingState]


def start_state(rules: Rules) -> ReadingState:
    return {
        "max_rounds": rules.reading.max_regenerations,
        "attempts": 0,
        "problem": None,
        "pending": {},
        "accepted": {},
        "feedback": {},
        "rejected": [],
        "rounds": 0,
        "error_code": None,
        "model": None,
        "critic_model": None,
    }


def _error_code(exc: Exception) -> str:
    return exc.code if isinstance(exc, NoModelConfiguredError) else "generation_failed"


async def _report(ctx: ReadingContext, stage: Stage) -> None:
    if ctx.report is not None:
        await ctx.report(stage)


def _sort_drafts(
    found: Sequence[QuestionDraft],
    positions: Sequence[int],
    paragraphs: Sequence[str],
    rng: random.Random,
    feedback: Feedback,
) -> tuple[dict[int, Question], Feedback]:
    """Checked questions for `positions`, and the positions that got none."""
    by_position: dict[int, QuestionDraft] = {}
    for found_draft in found:
        by_position.setdefault(found_draft.position, found_draft)
    pending: dict[int, Question] = {}
    feedback = dict(feedback)
    for position in positions:
        draft = by_position.get(position)
        if draft is None:
            feedback[position] = ({}, ["no question was written for this position"])
            continue
        shown = draft.model_dump(exclude={"position"})
        try:
            pending[position] = drafts.to_question(draft, paragraphs, rng)
        except drafts.DraftError as exc:
            feedback[position] = (shown, [f"invalid question: {exc}"])
            continue
        feedback.pop(position, None)
    return pending, feedback


async def rewrite(state: ReadingState, runtime: Runtime[ReadingContext]) -> dict[str, Any]:
    ctx = runtime.context
    rules = ctx.rules.reading
    attempts = state["attempts"] + 1
    await _report(ctx, "rewriting")
    try:
        reply = await ctx.rewrite(
            messages.rewrite_messages(
                ctx.title,
                ctx.source,
                level=ctx.level,
                words=rules.words[ctx.level],
                questions=rules.questions,
                problem=state["problem"],
            ),
            drafts.ArticleRewrite,
        )
    except Exception as exc:
        logger.warning("article rewrite call failed: %s", type(exc).__name__)
        return {"attempts": attempts, "error_code": _error_code(exc)}
    output = reply.output
    assert isinstance(output, drafts.ArticleRewrite)
    paragraphs = drafts.clean_paragraphs(output.paragraphs)
    problem = drafts.text_problem(paragraphs, rules.words[ctx.level], rules.length_slack)
    if problem is not None:
        return {"attempts": attempts, "problem": problem}
    positions = list(range(1, rules.questions + 1))
    rng = random.Random(ctx.seed)
    pending, feedback = _sort_drafts(output.questions, positions, paragraphs, rng, {})
    return {
        "attempts": attempts,
        "problem": None,
        "title": output.title.strip() or ctx.title,
        "paragraphs": paragraphs,
        "model": reply.model,
        "pending": pending,
        "feedback": feedback,
    }


def after_rewrite(state: ReadingState) -> str:
    if state["error_code"] is not None:
        return SAVE_NODE
    if state["problem"] is not None:
        return REWRITE_NODE if state["attempts"] < REWRITE_ATTEMPTS else SAVE_NODE
    return CRITIC_NODE if state["pending"] else _more_questions(state)


async def critic(state: ReadingState, runtime: Runtime[ReadingContext]) -> dict[str, Any]:
    ctx = runtime.context
    await _report(ctx, "reviewing")
    pending = state["pending"]
    try:
        reply = await ctx.critique(
            messages.critic_messages(
                state["title"],
                state["paragraphs"],
                level=ctx.level,
                questions=[pending[p] for p in sorted(pending)],
            ),
            drafts.QuestionReviews,
        )
    except Exception as exc:
        # Unchecked questions are never shown: drop them and stop asking for more.
        logger.warning("reading critic call failed: %s", type(exc).__name__)
        return {"pending": {}, "feedback": {}}
    output = reply.output
    assert isinstance(output, drafts.QuestionReviews)
    reviews = {review.position: review for review in output.reviews}
    accepted = dict(state["accepted"])
    feedback = dict(state["feedback"])
    rejected = list(state["rejected"])
    for position, question in pending.items():
        review = reviews.get(position)
        reasons = (
            drafts.rejection(question, review)
            if review is not None
            else ["the critic did not review it"]
        )
        if not reasons:
            accepted[position] = question
            continue
        feedback[position] = (question.stored(), reasons)
        rejected.append(
            {
                **question.stored(),
                "reasons": reasons,
                "review": review.model_dump() if review is not None else None,
            }
        )
    return {
        "pending": {},
        "accepted": accepted,
        "feedback": feedback,
        "rejected": rejected,
        "critic_model": reply.model,
    }


def _more_questions(state: ReadingState) -> str:
    rounds_left = state["rounds"] < state["max_rounds"]
    return QUESTIONS_NODE if state["feedback"] and rounds_left else SAVE_NODE


async def questions(state: ReadingState, runtime: Runtime[ReadingContext]) -> dict[str, Any]:
    ctx = runtime.context
    rounds = state["rounds"] + 1
    await _report(ctx, "fixing")
    feedback = state["feedback"]
    accepted = state["accepted"]
    try:
        reply = await ctx.questions(
            messages.questions_messages(
                state["title"],
                state["paragraphs"],
                level=ctx.level,
                kept=[accepted[p] for p in sorted(accepted)],
                rejected=feedback,
            ),
            drafts.QuestionSet,
        )
    except Exception as exc:
        logger.warning("reading questions call failed: %s", type(exc).__name__)
        return {"rounds": rounds, "feedback": {}}
    output = reply.output
    assert isinstance(output, drafts.QuestionSet)
    rng = random.Random(ctx.seed * 100 + rounds)
    pending, feedback = _sort_drafts(
        output.questions, sorted(feedback), state["paragraphs"], rng, feedback
    )
    return {"rounds": rounds, "pending": pending, "feedback": feedback}


def after_questions(state: ReadingState) -> str:
    return CRITIC_NODE if state["pending"] else _more_questions(state)


async def save(state: ReadingState, runtime: Runtime[ReadingContext]) -> dict[str, Any]:
    ctx = runtime.context
    if state["error_code"] is not None or state["problem"] is not None:
        result = RewriteResult(
            title=ctx.title,
            paragraphs=[],
            questions=[],
            rejected=[],
            model=None,
            critic_model=None,
            error_code=state["error_code"] or "rewrite_invalid",
        )
    else:
        accepted = state["accepted"]
        result = RewriteResult(
            title=state["title"],
            paragraphs=state["paragraphs"],
            questions=[accepted[p] for p in sorted(accepted)],
            rejected=state["rejected"],
            model=state["model"],
            critic_model=state["critic_model"],
        )
    await ctx.save(result)
    return {}


def build_reading_graph() -> ReadingGraph:
    graph = StateGraph(ReadingState, context_schema=ReadingContext)
    graph.add_node(REWRITE_NODE, rewrite)
    graph.add_node(CRITIC_NODE, critic)
    graph.add_node(QUESTIONS_NODE, questions)
    graph.add_node(SAVE_NODE, save)
    graph.add_edge(START, REWRITE_NODE)
    graph.add_conditional_edges(
        REWRITE_NODE, after_rewrite, [REWRITE_NODE, CRITIC_NODE, QUESTIONS_NODE, SAVE_NODE]
    )
    graph.add_conditional_edges(CRITIC_NODE, _more_questions, [QUESTIONS_NODE, SAVE_NODE])
    graph.add_conditional_edges(
        QUESTIONS_NODE, after_questions, [CRITIC_NODE, QUESTIONS_NODE, SAVE_NODE]
    )
    graph.add_edge(SAVE_NODE, END)
    return graph.compile()
