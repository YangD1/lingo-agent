"""Candidate study actions for the dashboard's advice (P1 plan §7.5.2).

The algorithm decides what to do; a model later only picks among these candidates and
writes the reasons. `signals` reads the numbers (plain SQL, no model call) and `rank`
turns them into scored candidates with rules from `rules.yaml` (`advice:`), so every
link and grammar point the learner is shown exists.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.evidence import CONVERSATION_SOURCES
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog, GrammarKC
from app.adaptive.rules import Rules
from app.advice import reminder
from app.advice.reminder import Reason, Reminder
from app.db.models import KCEvidence, KCMastery, PlacementSession
from app.services.vocab.books import Book, get_book
from app.services.vocab.progress import current
from app.services.vocab.queue import today_counts

Kind = Literal[
    "vocab_review", "vocab_learn", "vocab_screen", "placement", "grammar_practice", "choose_book"
]
KINDS: tuple[Kind, ...] = (
    "vocab_review",
    "vocab_learn",
    "vocab_screen",
    "placement",
    "grammar_practice",
    "choose_book",
)
# Mistake examples shown per grammar candidate.
EXAMPLES = 2


@dataclass(frozen=True, slots=True)
class Example:
    original: str
    correction: str | None


@dataclass(frozen=True, slots=True)
class WeakKC:
    kc: GrammarKC
    p_mastery: float
    # Counted mistakes in conversation within `advice.grammar_days`.
    mistakes: int
    # Most recent first.
    examples: tuple[Example, ...] = ()


@dataclass(frozen=True, slots=True)
class Signals:
    reviews_due: int
    new_left: int
    book: Book | None
    # The book's known-word screening has started (by hand or from the placement test).
    screened: bool
    # Whole days since the latest finished placement test; None if never finished.
    placement_days: int | None
    placement_in_progress: bool
    # Why to take the test now, if at all (task 50).
    reminder: Reminder | None
    weak_kcs: tuple[WeakKC, ...]


@dataclass(frozen=True, slots=True)
class Candidate:
    """One action with its evidence: what the model reads and the learner sees."""

    # Stable across refreshes: the kind, plus the KC for grammar practice.
    id: str
    kind: Kind
    score: float
    # Due words, new words left, or counted mistakes.
    count: int | None = None
    book: Book | None = None
    # Placement: days since the latest finished test (None = never), and a test is open.
    days_since: int | None = None
    in_progress: bool = False
    # Placement: the reminder's reason, the last test's level and that level's grammar
    # points learned out of all, and whether the learner said "Not now" to it lately.
    reason: Reason | None = None
    level: CefrLevel | None = None
    learned: int | None = None
    total: int | None = None
    snoozed: bool = False
    kc: GrammarKC | None = None
    p_mastery: float | None = None
    examples: tuple[Example, ...] = ()


def _saturating(n: float, half: float) -> float:
    return n / (n + half)


def rank(signals: Signals, rules: Rules) -> list[Candidate]:
    """The candidates, best first, at most `advice.max_candidates`."""
    ar = rules.advice
    p = ar.priority
    found: list[Candidate] = []

    if (r := signals.reminder) is not None:
        match r.reason:
            case "never":
                priority = p["placement"]
            case "resume":
                priority = p["placement"] if r.days_since is None else p["retest"]
            case "progress":
                priority = p["retest_progress"]
            case "age":
                priority = p["retest"]
        found.append(
            Candidate(
                "placement",
                "placement",
                priority,
                days_since=r.days_since,
                in_progress=r.reason == "resume",
                reason=r.reason,
                level=r.level,
                learned=r.learned,
                total=r.total,
                snoozed=r.snoozed,
            )
        )

    if signals.book is None:
        found.append(Candidate("choose_book", "choose_book", p["choose_book"]))
    elif not signals.screened:
        found.append(
            Candidate("vocab_screen", "vocab_screen", p["vocab_screen"], book=signals.book)
        )

    if signals.reviews_due:
        found.append(
            Candidate(
                "vocab_review",
                "vocab_review",
                p["vocab_review"] * _saturating(signals.reviews_due, ar.half["vocab_review"]),
                count=signals.reviews_due,
            )
        )
    if signals.new_left:
        found.append(
            Candidate(
                "vocab_learn",
                "vocab_learn",
                p["vocab_learn"] * _saturating(signals.new_left, ar.half["vocab_learn"]),
                count=signals.new_left,
                book=signals.book,
            )
        )

    grammar = [
        Candidate(
            f"grammar_practice:{weak.kc.id}",
            "grammar_practice",
            p["grammar_practice"]
            * _saturating(weak.mistakes * (1 - weak.p_mastery), ar.half["grammar_practice"]),
            count=weak.mistakes,
            kc=weak.kc,
            p_mastery=weak.p_mastery,
            examples=weak.examples[:EXAMPLES],
        )
        for weak in signals.weak_kcs
        if weak.mistakes and weak.p_mastery < rules.bkt.mastered
    ]
    grammar.sort(key=lambda c: (-c.score, c.id))
    found.extend(grammar[: ar.max_grammar])

    found.sort(key=lambda c: (-c.score, c.id))
    return found[: ar.max_candidates]


async def _weak_kcs(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime,
) -> tuple[WeakKC, ...]:
    """Grammar KCs with counted conversation mistakes lately; placement answers are tests."""
    counted = (
        KCEvidence.user_id == user_id,
        KCEvidence.correct.is_(False),
        KCEvidence.source.in_(CONVERSATION_SOURCES),
        KCEvidence.severity.in_(rules.evidence.counted_severities),
        KCEvidence.created_at >= now - timedelta(days=rules.advice.grammar_days),
    )
    counts = dict(
        (
            await session.execute(
                select(KCEvidence.kc_id, func.count()).where(*counted).group_by(KCEvidence.kc_id)
            )
        ).all()
    )
    kc_ids = [kc_id for kc_id in counts if catalog.get(kc_id) is not None]
    if not kc_ids:
        return ()
    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    p = dict(
        (
            await session.execute(
                select(KCMastery.kc_id, KCMastery.p_mastery).where(
                    KCMastery.user_id == user_id, KCMastery.kc_id.in_(kc_ids)
                )
            )
        ).all()
    )
    examples: dict[str, list[Example]] = defaultdict(list)
    rows = await session.execute(
        select(KCEvidence.kc_id, KCEvidence.original, KCEvidence.correction)
        .where(*counted, KCEvidence.kc_id.in_(kc_ids), KCEvidence.original.is_not(None))
        .order_by(KCEvidence.created_at.desc(), KCEvidence.id.desc())
    )
    for kc_id, original, correction in rows.all():
        if original and len(examples[kc_id]) < EXAMPLES:
            examples[kc_id].append(Example(original, correction))
    weak = []
    for kc_id in kc_ids:
        kc = catalog.get(kc_id)
        # A mistake always has a mastery row once evidence is replayed; be safe anyway.
        if kc is not None and kc_id in p:
            weak.append(WeakKC(kc, p[kc_id], counts[kc_id], tuple(examples[kc_id])))
    return tuple(weak)


async def signals(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> Signals:
    """May rebuild stale mastery rows first; the caller commits."""
    now = now or datetime.now(UTC)
    counts = await today_counts(session, user_id, rules=rules, tz=tz, now=now)
    plan = await current(session, user_id)
    finished = await session.scalar(
        select(func.max(PlacementSession.finished_at)).where(
            PlacementSession.user_id == user_id, PlacementSession.status == "done"
        )
    )
    open_test = await session.scalar(
        select(PlacementSession.id)
        .where(PlacementSession.user_id == user_id, PlacementSession.status == "in_progress")
        .limit(1)
    )
    return Signals(
        reviews_due=counts.reviews_due,
        new_left=counts.new_left,
        book=get_book(plan.book_id) if plan else None,
        screened=bool(plan and plan.screen_offset),
        placement_days=(now - finished).days if finished else None,
        placement_in_progress=open_test is not None,
        reminder=await reminder.current(session, user_id, rules=rules, catalog=catalog, now=now),
        weak_kcs=await _weak_kcs(session, user_id, rules=rules, catalog=catalog, now=now),
    )


async def candidates(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> list[Candidate]:
    found = await signals(session, user_id, rules=rules, catalog=catalog, tz=tz, now=now)
    return rank(found, rules)
