"""The quiz card (ADR 0044 §4): `give_quiz` starts a set on one KC and shows a card
the learner answers in the chat; the set's results go back to the tutor as data.

Generating takes far longer than a tool call may (the chat's tool timeout), so the
call only creates the set and returns; the card polls the set like the practice page
does, and answers go through the practice API. The same tool call id gives the same
set and card.
"""

import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
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
from app.adaptive.exercise.worker import QuizLimitError
from app.adaptive.kc.catalog import get_grammar_catalog
from app.cards.tools import CardDraft, CardScope, GiveQuiz, ToolCallError, parse_args
from app.db.models import Attempt, Exercise, ExerciseSet, TutorCard

# Starts generating a set: (user, tenant, KC, purpose) -> set id; PracticeWorker.start_quiz.
type StartQuiz = Callable[[uuid.UUID, uuid.UUID, str, QuizPurpose], Awaitable[uuid.UUID]]

# Answers quoted per wrong item, so a long answer does not fill the prompt.
_QUOTE = 160


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
    ) -> None:
        self._sessionmaker = sessionmaker
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
        kc = get_grammar_catalog().get(parsed.kc_id)
        if kc is None:
            raise ToolCallError(f"unknown kc_id {parsed.kc_id!r}")
        if scope is not None and scope.kc_ids is not None and kc.id not in scope.kc_ids:
            raise ToolCallError(f"kc_id {kc.id!r} is not a grammar point of this conversation")
        async with self._sessionmaker() as session:
            earlier = await session.scalar(
                select(TutorCard.params).where(
                    TutorCard.conversation_id == self._conversation_id,
                    TutorCard.tool_call_id == call_id,
                )
            )
        if earlier is not None:
            set_id = uuid.UUID(earlier["set_id"])
        else:
            try:
                set_id = await self._start(self._user_id, self._tenant_id, kc.id, parsed.purpose)
            except QuizLimitError as exc:
                raise ToolCallError(
                    "the learner has already taken today's pass quizzes on this grammar "
                    "point; suggest trying again tomorrow, and keep practising in the chat"
                ) from exc
        what = "an understanding check" if parsed.purpose == "check" else "the pass quiz"
        return QuizResult(
            f"Quiz card shown: {what} on {kc.name_en}. Its questions are being written and "
            "checked; the learner answers them in the card, and you will see the results "
            "in your context. Do not ask the questions or give answers in your reply: "
            "tell the learner briefly to try the card.",
            CardDraft("quiz", {"set_id": str(set_id), "kc_id": kc.id, "purpose": parsed.purpose}),
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
            return "could not be made; ask the learner a question or two yourself"
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
