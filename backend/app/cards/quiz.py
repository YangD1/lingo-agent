"""The quiz card (ADR 0044 §4): `give_quiz` starts a set on one KC and shows a card
the learner answers in the chat; the set's results go back to the tutor as data.

Generating takes far longer than a tool call may (the chat's tool timeout), so the
call only creates the set and returns; the card polls the set like the practice page
does, and answers go through the practice API. The same tool call id gives the same
set and card.
"""

import uuid
from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.exercise.formats import (
    Choice4,
    Cloze,
    ConceptChoice,
    ExerciseBody,
    Explain,
    FindFix,
    RewriteOwn,
    Transform,
    Translate,
    parse_body,
)
from app.adaptive.exercise.planner import QuizPurpose
from app.adaptive.exercise.worker import QuizStart
from app.adaptive.kc.catalog import GrammarKC, get_grammar_catalog
from app.adaptive.kc.search import find_kcs, is_clear
from app.adaptive.rules import get_rules
from app.cards.tools import CardDraft, CardScope, GiveQuiz, ToolCallError, parse_args
from app.db.models import Attempt, Exercise, ExerciseSet, TutorCard


class StartQuiz(Protocol):
    """PracticeWorker.start_quiz: an unfinished set on the KC, or a new one."""

    async def __call__(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        kc_id: str,
        purpose: QuizPurpose,
        *,
        fresh: bool = False,
    ) -> QuizStart: ...


# Answers quoted per wrong item, so a long answer does not fill the prompt.
_QUOTE = 160
# Grammar points offered back when a topic matches several (ADR 0046 §1).
_CANDIDATES = 5


@dataclass(frozen=True)
class QuizResult:
    content: str
    draft: CardDraft


class QuizTools:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        start: StartQuiz,
        proactive: bool = True,
        lesson: bool = False,
    ) -> None:
        self._sessionmaker = sessionmaker
        # The learner lets the tutor give quizzes nobody asked for (ADR 0046 §4); in a
        # lesson, which the learner opened to be taught and tested, any quiz goes.
        self._proactive = proactive
        self._lesson = lesson
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._conversation_id = conversation_id
        self._start = start

    async def run(
        self, args: Mapping[str, Any], call_id: str, scope: CardScope | None
    ) -> QuizResult:
        """Raises ToolCallError, whose message goes back to the model."""
        parsed = parse_args("give_quiz", args)
        assert isinstance(parsed, GiveQuiz)
        within = scope.kc_ids if scope is not None else None
        kc = _grammar_point(parsed, within)
        async with self._sessionmaker() as session:
            earlier = await session.scalar(
                select(TutorCard.params).where(
                    TutorCard.conversation_id == self._conversation_id,
                    TutorCard.tool_call_id == call_id,
                )
            )
        if earlier is not None:
            started = QuizStart(uuid.UUID(earlier["set_id"]), resumed=False)
        else:
            if not parsed.asked and not self._lesson:
                await self._check_unasked(parsed, kc)
            started = await self._start(
                self._user_id, self._tenant_id, kc.id, parsed.purpose, fresh=parsed.fresh
            )
        set_id = started.set_id
        what = "an understanding check" if parsed.purpose == "check" else "the pass quiz"
        if started.resumed:
            async with self._sessionmaker() as session:
                state = (await quiz_states(session, [set_id]))[set_id]
            shown = (
                f"Quiz card shown again: the learner's unfinished {what} on {kc.name_en} "
                f"({state.describe(parsed.purpose, get_rules().course.pass_score)}), so they "
                "carry on where they stopped. If they want new questions instead, call "
                "give_quiz again with fresh true."
            )
        else:
            shown = (
                f"Quiz card shown: {what} on {kc.name_en}. Its questions are being written "
                "and checked."
            )
        return QuizResult(
            f"{shown} The learner answers them in the card, and you will see the results "
            "in your context. Do not ask the questions or give answers in your reply: "
            "tell the learner briefly to try the card.",
            CardDraft(
                "quiz",
                {
                    "set_id": str(set_id),
                    "kc_id": kc.id,
                    "purpose": parsed.purpose,
                    "proactive": not parsed.asked,
                },
            ),
        )

    async def _check_unasked(self, parsed: GiveQuiz, kc: GrammarKC) -> None:
        """A quiz the learner did not ask for (ADR 0046 §3). Raises ToolCallError."""
        if not self._proactive:
            raise ToolCallError(
                "the learner turned off quizzes they did not ask for; ask in your reply "
                "whether they want one"
            )
        if parsed.purpose == "quiz":
            raise ToolCallError(
                "a pass quiz counts toward mastery, so give one only when the learner asks "
                "for it or agrees to it; use purpose check, or ask first"
            )
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(TutorCard.params, TutorCard.created_at).where(
                        TutorCard.conversation_id == self._conversation_id,
                        TutorCard.kind == "quiz",
                        TutorCard.params["proactive"].as_boolean(),
                    )
                )
            ).all()
            now = await session.scalar(select(func.now()))
        if any(params["kc_id"] == kc.id for params, _ in rows):
            raise ToolCallError(
                f"you already gave an unasked check on {kc.name_en} in this conversation; "
                "ask in your reply instead"
            )
        gap = timedelta(minutes=get_rules().course.proactive_quiz_gap_minutes)
        if now is not None and any(now - at < gap for _, at in rows):
            raise ToolCallError(
                "you gave an unasked quiz only a few minutes ago; ask in your reply instead"
            )


def _grammar_point(parsed: GiveQuiz, within: Collection[str] | None) -> GrammarKC:
    """The call's KC, by id or by name (ADR 0046 §1). Raises ToolCallError."""
    catalog = get_grammar_catalog()
    kc = catalog.get(parsed.kc_id) if parsed.kc_id else None
    if kc is not None:
        if within is not None and kc.id not in within:
            raise ToolCallError(f"kc_id {kc.id!r} is not a grammar point of this conversation")
        return kc
    # Models write a name into kc_id, or an id without its prefix: search for it.
    topic = parsed.topic or (parsed.kc_id or "").removeprefix("g.").replace("_", " ")
    matches = find_kcs(catalog, topic, within)
    if is_clear(matches):
        return matches[0].kc
    if not matches:
        raise ToolCallError(
            f"no grammar point matches {topic!r}; try another name in English, or "
            "ask the questions in your reply if the test is not on one grammar point"
        )
    listed = "; ".join(f"{m.kc.id} ({m.kc.name_en})" for m in matches[:_CANDIDATES])
    raise ToolCallError(
        f"{topic!r} matches several grammar points: {listed}. "
        "Call give_quiz again now with the kc_id of the one closest to what you were "
        "teaching; do not write the questions yourself."
    )


# --- results, for the tutor's context ---------------------------------------------------


def _question(body: ExerciseBody) -> str:
    match body:
        case Choice4() | Cloze():
            return body.content.stem
        case ConceptChoice() | Explain():
            return body.content.question
        case FindFix():
            return f"find and fix the error: {body.content.sentence}"
        case Transform():
            return f"{body.content.instruction} {body.content.source}"
        case Translate():
            return f"translate: {body.content.source}"
        case RewriteOwn():
            return f"{body.content.instruction} {body.content.original}"
    return ""  # pragma: no cover


def _key(body: ExerciseBody) -> str:
    match body:
        case Choice4() | ConceptChoice():
            return body.answer.correct
        case Explain():
            return "; ".join(body.answer.key_points)
        case FindFix():
            return f"replace {body.content.segments[body.answer.wrong_segment]!r} with " + (
                f"{body.answer.accepted[0]!r}"
            )
        case _:
            return body.answer.accepted[0]


def _given(response: Mapping[str, Any]) -> str:
    if "segment" in response:
        return f"piece {response['segment']} -> {response.get('fix', '')!r}"
    text = str(response.get("choice") or response.get("text") or "")
    return text if len(text) <= _QUOTE else text[:_QUOTE] + "…"


@dataclass(frozen=True, slots=True)
class QuizState:
    status: str
    total: int
    answered: int
    correct: int
    # Wrong first answers: question, the learner's answer, the key.
    wrong: tuple[tuple[str, str, str], ...]

    def describe(self, purpose: str, pass_score: float) -> str:
        if self.status == "generating":
            return "questions still being written"
        if self.status == "failed":
            return (
                "could not be made; if the learner still wants it, call give_quiz again "
                "with fresh true"
            )
        if self.answered < self.total:
            return f"{self.answered} of {self.total} answered so far"
        text = f"all answered, {self.correct} of {self.total} right"
        if purpose == "quiz" and self.total:
            met = self.correct / self.total >= pass_score
            text += f" (score {'meets' if met else 'is below'} the pass mark)"
        for question, given, key in self.wrong:
            text += f"; missed: {question!r}, answered {given!r}, expected {key!r}"
        return text


async def quiz_states(
    session: AsyncSession, set_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, QuizState]:
    """Where each quiz set stands, by set id."""
    ids = list(set_ids)
    if not ids:
        return {}
    statuses = dict(
        (
            await session.execute(
                select(ExerciseSet.id, ExerciseSet.status).where(ExerciseSet.id.in_(ids))
            )
        ).all()
    )
    rows = await session.execute(
        select(Exercise, Attempt)
        .outerjoin(Attempt, Attempt.exercise_id == Exercise.id)
        .where(Exercise.set_id.in_(ids), Exercise.status == "ok")
        .order_by(Exercise.set_id, Exercise.position, Attempt.id)
    )
    first: dict[int, tuple[Exercise, Attempt | None]] = {}
    for row, answer in rows.all():
        first.setdefault(row.id, (row, answer))
    total: Counter[uuid.UUID] = Counter()
    answered: Counter[uuid.UUID] = Counter()
    correct: Counter[uuid.UUID] = Counter()
    wrong: dict[uuid.UUID, list[tuple[str, str, str]]] = {i: [] for i in statuses}
    for item, attempt in first.values():
        total[item.set_id] += 1
        if attempt is None:
            continue
        answered[item.set_id] += 1
        if attempt.correct:
            correct[item.set_id] += 1
        else:
            body = parse_body(item.format, item.content, item.answer)
            wrong[item.set_id].append((_question(body), _given(attempt.response), _key(body)))
    return {
        set_id: QuizState(
            status, total[set_id], answered[set_id], correct[set_id], tuple(wrong[set_id])
        )
        for set_id, status in statuses.items()
    }
