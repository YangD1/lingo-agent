"""The grammar course (ADR 0044): the lessons in order, each with its state."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.adaptive import course
from app.adaptive.course import LessonState
from app.adaptive.kc.catalog import CefrLevel, get_grammar_catalog
from app.adaptive.rules import get_rules
from app.deps import CurrentUser, SessionDep

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
