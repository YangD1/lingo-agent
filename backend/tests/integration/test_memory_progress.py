"""Where the learner stands now (ADR 0052 §1): counted from their own records."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.advice.candidates import Candidate, Example
from app.db.models import (
    Article,
    ExerciseSet,
    Feed,
    LLMUsage,
    ReadingSession,
    Tenant,
    User,
    UserCard,
    UserWordBook,
    Word,
)
from app.memory.progress import (
    BookPosition,
    LessonPosition,
    Progress,
    QuizResult,
    Reading,
    load_progress,
    render_progress,
)
from app.services.news.sources import sync_builtin_feeds
from tests.integration.test_quiz_tools import KC, answer

CATALOG = get_grammar_catalog()
RULES = get_rules()
NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


async def _learner(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = Tenant(name="t", kind="personal")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    return user.id, tenant.id


async def _quiz(
    session: AsyncSession,
    user_id: uuid.UUID,
    rights: list[bool | None],
    *,
    minutes_ago: int,
    purpose: str = "quiz",
    status: str = "ready",
) -> uuid.UUID:
    row = ExerciseSet(
        user_id=user_id,
        origin="quiz",
        quiz_purpose=purpose,
        status=status,
        kc_plan=[],
        focus_kc_id=KC,
        created_at=NOW - timedelta(minutes=minutes_ago),
    )
    session.add(row)
    await session.flush()
    if rights:
        await answer(session, row.id, rights)
    if status == "failed":  # `answer` moves it on
        row.status = "failed"
        await session.flush()
    return row.id


async def _article(session: AsyncSession, title: str) -> Article:
    feed = await session.scalar(select(Feed).where(Feed.builtin_key.is_not(None)))
    assert feed is not None
    article = Article(
        feed_id=feed.id,
        guid=title,
        url=f"https://example.com/{uuid.uuid4()}",
        title=title,
        published_at=NOW - timedelta(days=1),
        body="One.\n\nTwo.",
        summary_only=False,
        license=feed.license,
        word_count=2,
    )
    session.add(article)
    await session.flush()
    return article


async def test_a_new_learner_has_only_the_course_start(db_session: AsyncSession) -> None:
    me, _ = await _learner(db_session)

    progress = await load_progress(db_session, me, rules=RULES, catalog=CATALOG, now=NOW)

    assert progress.lesson is not None and progress.lesson.number == 1
    assert (list(progress.quizzes), progress.book, list(progress.readings)) == ([], None, [])
    assert progress.studied_days == 0 and progress.last_before_today is None
    text = render_progress(progress)
    assert "- Grammar course: on lesson 1 of" in text
    assert "last before today: never before today" in text


async def test_counts_quizzes_book_reading_and_days(db_session: AsyncSession) -> None:
    me, tenant = await _learner(db_session)
    other, _ = await _learner(db_session)
    await _quiz(db_session, me, [True, False, True], minutes_ago=50)
    await _quiz(db_session, me, [True, None, None], minutes_ago=40, purpose="check")
    await _quiz(db_session, me, [], minutes_ago=30)  # still being written: nothing to show
    await _quiz(db_session, me, [None, None], minutes_ago=20, status="failed")  # withdrawn
    await _quiz(db_session, me, [None, None], minutes_ago=10)
    await _quiz(db_session, other, [True], minutes_ago=5)  # someone else's
    words = [Word(word=f"w{i}", translation="释义", tags=["cet4"], frq=i) for i in range(4)]
    db_session.add_all([*words, UserWordBook(user_id=me, book_id="cet4")])
    await db_session.flush()
    db_session.add_all(
        [
            UserCard(
                user_id=me,
                word_id=words[0].id,
                source="book",
                status="learning",
                state=2,
                stability=5.0,
                due=NOW,
            ),
            UserCard(user_id=me, word_id=words[1].id, source="book", status="known"),
        ]
    )
    await sync_builtin_feeds(db_session)
    done, open_ = await _article(db_session, "Comets"), await _article(db_session, "Rockets")
    db_session.add_all(
        [
            ReadingSession(
                user_id=me,
                article_id=done.id,
                level="A2",
                started_at=NOW - timedelta(days=3),
                finished_at=NOW - timedelta(days=3),
            ),
            ReadingSession(
                user_id=me, article_id=open_.id, level="A2", started_at=NOW - timedelta(days=1)
            ),
            LLMUsage(
                tenant_id=tenant,
                user_id=me,
                task="chat",
                connection_name="c",
                model="m",
                latency_ms=1,
                status="ok",
                created_at=NOW - timedelta(days=2),
            ),
        ]
    )
    await db_session.flush()

    progress = await load_progress(db_session, me, rules=RULES, catalog=CATALOG, now=NOW)

    assert [(q.purpose, q.total, q.answered, q.correct) for q in progress.quizzes] == [
        ("quiz", 2, 0, 0),
        ("check", 3, 1, 1),
        ("quiz", 3, 3, 2),
    ]
    assert progress.book is not None
    assert (progress.book.total, progress.book.learning, progress.book.known) == (4, 1, 1)
    assert [(r.title, r.finished) for r in progress.readings] == [
        ("Rockets", False),
        ("Comets", True),
    ]
    assert progress.studied_days == 1
    text = render_progress(progress)
    assert "2 questions, none answered yet" in text
    assert "understanding check, 1 of 3 answered (1 right), not finished" in text
    assert "pass quiz, finished: 2 of 3 right" in text
    assert "- Word book: CET-4, 4 words; 1 being learned, 1 marked known" in text
    assert '"Rockets" (not finished); "Comets" (finished)' in text
    assert "last before today: 2 days ago" in text
    assert "Days studied" not in render_progress(progress, days=False)


def test_the_section_stays_short() -> None:
    """The worst case the loader allows: three quizzes on the longest-named point,
    two titles at the cut."""
    kc = max(CATALOG.kcs, key=lambda k: len(k.id) + len(k.name_en))
    progress = Progress(
        today=NOW.date(),
        lesson=LessonPosition(119, kc, 118, 119),
        quizzes=[QuizResult(kc, "check", 10, 9, 8)] * 3,
        book=BookPosition("Oxford 3000", 3000, 2999, 2999),
        readings=[Reading("x" * 80, False)] * 2,
        studied_days=7,
        last_before_today=NOW.date() - timedelta(days=1),
    )

    assert len(render_progress(progress)) <= 900


async def test_free_chat_gets_the_engines_next_steps(db_session: AsyncSession) -> None:
    """ADR 0054 §4: a new learner is told to take the placement test and choose a book,
    each with the card for it; other conversations don't get them."""
    me, _ = await _learner(db_session)

    progress = await load_progress(
        db_session, me, rules=RULES, catalog=CATALOG, now=NOW, suggest=True
    )
    plain = await load_progress(db_session, me, rules=RULES, catalog=CATALOG, now=NOW)

    assert 0 < len(progress.suggestions) <= 2
    assert not any(c.snoozed for c in progress.suggestions)
    assert not plain.suggestions
    text = render_progress(progress)
    assert "- Suggested next by the learning engine, best first" in text
    assert "card: `suggest_link` with `placement`" in text
    assert "Suggested next" not in render_progress(plain)


def test_a_grammar_suggestion_names_its_practice_card() -> None:
    kc = CATALOG.get(KC)
    assert kc is not None
    progress = Progress(
        today=NOW.date(),
        suggestions=[
            Candidate(
                id="grammar_practice:x",
                kind="grammar_practice",
                score=1.0,
                count=3,
                kc=kc,
                p_mastery=0.2,
                examples=(Example("He go home.", "He goes home."),),
            )
        ],
    )

    text = render_progress(progress)

    assert f"card: `suggest_practice` with `{KC}`" in text
    # The mistake sits under its suggestion.
    assert '\n    - mistake: "He go home." -> "He goes home."' in text
