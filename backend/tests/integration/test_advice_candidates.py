"""What the advice candidates read from the database (P1 plan §7.5.2)."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice.candidates import Signals, candidates, signals
from app.db.models import KCEvidence, PlacementSession, UserCard, UserWordBook, Word
from tests.integration.test_dashboard import new_user

RULES = get_rules()
CATALOG = get_grammar_catalog()
UTC_ZONE = ZoneInfo("UTC")
NOW = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)
THIRD_PERSON = "g.present_simple_third_person"
ARTICLES = "g.articles_basic"


async def read(session: AsyncSession, user_id: uuid.UUID) -> Signals:
    return await signals(session, user_id, rules=RULES, catalog=CATALOG, tz=UTC_ZONE, now=NOW)


def placement(user_id: uuid.UUID, finished: datetime | None) -> PlacementSession:
    """A finished test, or an open one without `finished`."""
    row = PlacementSession(
        user_id=user_id,
        status="done" if finished else "in_progress",
        stage="grammar",
        seed=1,
        rules_version="x",
        finished_at=finished,
    )
    if finished:
        row.result = {"cefr": "B1", "vocab": {}, "grammar": {}, "answers": {}}
    return row


async def test_a_new_learner(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)

    s = await read(db_session, user_id)

    assert s == Signals(0, 0, None, False, None, False, ())
    found = await candidates(
        db_session, user_id, rules=RULES, catalog=CATALOG, tz=UTC_ZONE, now=NOW
    )
    assert [c.id for c in found] == ["placement", "choose_book"]


async def test_book_words_and_the_latest_finished_test(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)
    words = [Word(word=f"w{i}", translation="释义", tags=["cet4"], frq=i) for i in range(3)]
    db_session.add_all(words)
    db_session.add(UserWordBook(user_id=user_id, book_id="cet4", screen_offset=500))
    await db_session.flush()
    db_session.add_all(
        [
            UserCard(
                user_id=user_id,
                word_id=words[0].id,
                source="book",
                status="learning",
                state=2,
                stability=3.0,
                due=NOW - timedelta(hours=1),
            ),
            placement(user_id, NOW - timedelta(days=90)),
            placement(user_id, NOW - timedelta(days=61, hours=1)),
            placement(user_id, None),
        ]
    )
    await db_session.flush()

    s = await read(db_session, user_id)

    assert s.book is not None and s.book.id == "cet4" and s.screened
    # One due card; two book words without cards are today's new words.
    assert (s.reviews_due, s.new_left) == (1, 2)
    assert (s.placement_days, s.placement_in_progress) == (61, True)


async def test_recent_counted_conversation_mistakes_make_weak_kcs(
    db_session: AsyncSession,
) -> None:
    user_id, _ = await new_user(db_session)
    recent = NOW - timedelta(days=1)

    def mistake(
        kc_id: str,
        *,
        at: datetime = recent,
        source: str = "chat",
        severity: str = "medium",
        original: str | None = "he go",
    ) -> KCEvidence:
        return KCEvidence(
            user_id=user_id,
            kc_id=kc_id,
            correct=False,
            evidence="production" if source == "chat" else "recognition",
            source=source,
            error_type="omission",
            severity=severity,
            original=original,
            correction="he goes" if original else None,
            created_at=at,
        )

    db_session.add_all(
        [
            mistake(THIRD_PERSON, original="she like it", at=recent - timedelta(hours=2)),
            mistake(THIRD_PERSON, original="he go", at=recent),
            mistake(THIRD_PERSON, original="it work", at=recent - timedelta(hours=1)),
            # Not counted: a placement answer, a low-severity slip, too long ago, not in
            # the catalog.
            mistake(ARTICLES, source="placement", original=None),
            mistake(ARTICLES, severity="low"),
            mistake(ARTICLES, at=NOW - timedelta(days=RULES.advice.grammar_days + 1)),
            mistake("g.not_in_the_catalog"),
        ]
    )
    await db_session.flush()
    await mastery.rebuild(db_session, user_id, rules=RULES, catalog=CATALOG)

    s = await read(db_session, user_id)

    assert [(w.kc.id, w.mistakes) for w in s.weak_kcs] == [(THIRD_PERSON, 3)]
    weak = s.weak_kcs[0]
    assert 0 < weak.p_mastery < RULES.bkt.weak
    # The two most recent, newest first.
    assert [e.original for e in weak.examples] == ["he go", "it work"]
    assert weak.examples[0].correction == "he goes"
