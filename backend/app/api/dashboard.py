"""The ability dashboard (P1 plan §7.5.1): one aggregate of the learner's own data."""

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from app.adaptive.kc.catalog import CefrLevel, get_grammar_catalog
from app.adaptive.rules import get_rules
from app.api.vocab import TimeZone
from app.dashboard import service
from app.deps import CurrentUser, SessionDep
from app.services.vocab.scheduler import learner_zone

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class SummaryOut(BaseModel):
    cefr: CefrLevel | None
    vocab_size: int | None
    vocab_cefr: CefrLevel | None
    vocab_reliable: bool | None
    streak_days: int
    studied_today: bool
    reviews_due: int
    new_left: int


class BookOut(BaseModel):
    id: str
    name_zh: str
    name_en: str
    total: int
    mastered: int
    learning: int
    known: int
    unlearned: int


class LevelOut(BaseModel):
    total: int
    mastered: int
    learning: int
    weak: int
    unseen: int


class SkillOut(BaseModel):
    skill: str
    cefr: CefrLevel | None
    # 0 to 6 on one CEFR scale: A1 covers [0, 1) … C2 [5, 6]; None when not mappable.
    position: float | None
    attempts: int
    vocab_size: int | None
    reliable: bool | None


class ErrorOut(BaseModel):
    kc_id: str
    name_en: str
    name_zh: str
    cefr: CefrLevel
    mistakes: int


class DayOut(BaseModel):
    date: date
    reviews: int
    turns: int


class DashboardOut(BaseModel):
    summary: SummaryOut
    # None until a word book is chosen.
    book: BookOut | None
    grammar: dict[CefrLevel, LevelOut]
    skills: list[SkillOut]
    errors: list[ErrorOut]
    days: list[DayOut]


@router.get("")
async def get_dashboard(
    user: CurrentUser, session: SessionDep, tz: TimeZone = None
) -> DashboardOut:
    board = await service.dashboard(
        session,
        user.id,
        rules=get_rules(),
        catalog=get_grammar_catalog(),
        tz=await learner_zone(session, user.id, tz),
    )
    await session.commit()  # stale mastery rows may have been rebuilt
    s, book = board.summary, board.book
    return DashboardOut(
        summary=SummaryOut(
            cefr=s.cefr,
            vocab_size=s.vocab_size,
            vocab_cefr=s.vocab_cefr,
            vocab_reliable=s.vocab_reliable,
            streak_days=s.streak_days,
            studied_today=s.studied_today,
            reviews_due=s.reviews_due,
            new_left=s.new_left,
        ),
        book=BookOut(
            id=book.book.id,
            name_zh=book.book.name_zh,
            name_en=book.book.name_en,
            total=book.total,
            mastered=book.mastered,
            learning=book.learning,
            known=book.known,
            unlearned=book.unlearned,
        )
        if book
        else None,
        grammar={
            level: LevelOut(
                total=split.total,
                mastered=split.mastered,
                learning=split.learning,
                weak=split.weak,
                unseen=split.unseen,
            )
            for level, split in board.grammar.items()
        },
        skills=[
            SkillOut(
                skill=p.skill,
                cefr=p.cefr,
                position=p.position,
                attempts=p.attempts,
                vocab_size=p.vocab_size,
                reliable=p.reliable,
            )
            for p in board.skills
        ],
        errors=[
            ErrorOut(
                kc_id=e.kc.id,
                name_en=e.kc.name_en,
                name_zh=e.kc.name_zh,
                cefr=e.kc.cefr,
                mistakes=e.mistakes,
            )
            for e in board.errors
        ],
        days=[DayOut(date=d.day, reviews=d.reviews, turns=d.turns) for d in board.days],
    )
