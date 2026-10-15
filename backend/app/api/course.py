"""The grammar course (ADR 0044): the lessons in order, each with its state; starting a
lesson, and testing out of one."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.adaptive import course
from app.adaptive.course import LessonState
from app.adaptive.exercise.worker import PracticeWorker, QuizLimitError
from app.adaptive.kc.catalog import CefrLevel, GrammarKC, get_grammar_catalog
from app.adaptive.rules import get_rules
from app.api.chat import ConversationOut
from app.api.errors import api_error
from app.cards import service as cards
from app.cards.tools import CardDraft
from app.chat import service as chat
from app.db.models import Conversation
from app.deps import CurrentTenant, CurrentUser, SessionDep, per_user
from app.memory.reflection import LOCALE_COOKIE, memory_language
from app.memory.worker import ReflectionWorker

router = APIRouter(prefix="/course", tags=["course"])


class LessonOut(BaseModel):
    number: int
    kc_id: str
    name_en: str
    name_zh: str
    cefr: CefrLevel
    state: LessonState
    p_mastery: float
    # Share right in the latest finished pass quiz; null before one.
    quiz_score: float | None
    # Prerequisites still to pass while the lesson is locked.
    blocked_by: list[str]


class CourseOut(BaseModel):
    level: CefrLevel | None
    current: str | None
    pass_score: float
    lessons: list[LessonOut]


@router.get("")
async def get_course(user: CurrentUser, session: SessionDep) -> CourseOut:
    rules = get_rules()
    found = await course.load(
        session, user.id, rules=rules, catalog=get_grammar_catalog(), now=datetime.now(UTC)
    )
    await session.commit()  # stale mastery rows may have been rebuilt
    return CourseOut(
        level=found.level,
        current=found.current,
        pass_score=rules.course.pass_score,
        lessons=[
            LessonOut(
                number=lesson.number,
                kc_id=lesson.kc.id,
                name_en=lesson.kc.name_en,
                name_zh=lesson.kc.name_zh,
                cefr=lesson.kc.cefr,
                state=lesson.state,
                p_mastery=lesson.p_mastery,
                quiz_score=lesson.quiz_score,
                blocked_by=list(lesson.blocked_by),
            )
            for lesson in found.lessons
        ],
    )


class LessonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The UI's locale, for a new lesson's title.
    locale: Annotated[str | None, Field(max_length=10)] = None


class LessonStarted(BaseModel):
    conversation: ConversationOut


class TestedOut(BaseModel):
    conversation: ConversationOut
    # The quiz card, as GET /conversations/{id}/cards lists it.
    card: dict[str, Any]


KcPath = Annotated[str, Path(max_length=64)]


def _kc(kc_id: str) -> GrammarKC:
    kc = get_grammar_catalog().get(kc_id)
    if kc is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "lesson_not_found", "no such lesson")
    return kc


async def _lesson(
    request: Request,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    kc: GrammarKC,
    body: LessonIn | None,
) -> Conversation:
    """The learner's latest lesson conversation on `kc`, or a new one (201)."""
    found = await chat.latest_lesson(session, user.id, kc.id)
    if found is not None:
        response.status_code = status.HTTP_200_OK
        return found
    locale = (body.locale if body else None) or request.cookies.get(LOCALE_COOKIE)
    created = await chat.create_conversation(
        session, tenant.id, user.id, focus=kc, purpose="lesson", locale=locale
    )
    # Starting afresh is when the conversation the learner left gets its summary.
    worker: ReflectionWorker = request.app.state.reflection_worker
    await worker.finish_previous(
        user.id,
        except_conversation_id=created.id,
        language=memory_language(request.cookies.get(LOCALE_COOKIE)),
    )
    return created


@router.post(
    "/lessons/{kc_id}",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "the lesson's latest conversation, continued"},
        404: {"description": "lesson_not_found"},
        409: {"description": "lesson_locked"},
    },
)
async def start_lesson(
    kc_id: KcPath,
    request: Request,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    body: LessonIn | None = None,
) -> LessonStarted:
    """Start or continue a lesson (ADR 0044 §5). A locked lesson can only be tested out
    of; the tutor speaks first through POST /conversations/{id}/opening."""
    kc = _kc(kc_id)
    whole = await course.load(
        session, user.id, rules=get_rules(), catalog=get_grammar_catalog(), now=datetime.now(UTC)
    )
    lesson = whole.lesson(kc.id)
    if lesson is not None and lesson.state == "locked":
        await session.rollback()
        raise api_error(
            status.HTTP_409_CONFLICT,
            "lesson_locked",
            "Pass the lessons this one builds on first, or test out of it.",
        )
    await session.commit()  # stale mastery rows may have been rebuilt
    conversation = await _lesson(request, response, user, tenant, session, kc, body)
    return LessonStarted(conversation=ConversationOut.of(conversation))


@router.post(
    "/lessons/{kc_id}/test-out",
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_user("generate")],
    responses={
        200: {"description": "in the lesson's latest conversation"},
        404: {"description": "lesson_not_found"},
        409: {"description": "quiz_limit"},
    },
)
async def test_out(
    kc_id: KcPath,
    request: Request,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    body: LessonIn | None = None,
) -> TestedOut:
    """The learner says they know it already (ADR 0044 §5): a pass quiz card in the lesson's
    conversation, without a turn of the chat model; only the quiz is generated. Locked
    lessons too."""
    kc = _kc(kc_id)
    conversation = await _lesson(request, response, user, tenant, session, kc, body)
    worker: PracticeWorker = request.app.state.practice_worker
    try:
        set_id = await worker.start_quiz(user.id, tenant.id, kc.id, "quiz")
    except QuizLimitError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "quiz_limit",
            "You have taken today's pass quizzes on this grammar point. Try again tomorrow.",
        ) from exc
    turn = f"test-out-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
    card = await cards.put_card(
        session,
        user_id=user.id,
        conversation_id=conversation.id,
        turn_id=turn,
        tool_call_id=turn,
        draft=CardDraft("quiz", {"set_id": str(set_id), "kc_id": kc.id, "purpose": "quiz"}),
    )
    return TestedOut(conversation=ConversationOut.of(conversation), card=cards.card_json(card))
