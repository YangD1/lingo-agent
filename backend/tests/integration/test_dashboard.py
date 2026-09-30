"""The ability dashboard's aggregates (P1 plan §7.5.1, Q17a to Q17d)."""

import math
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.kc.catalog import CEFR_LEVELS, get_grammar_catalog
from app.adaptive.placement.flow import vocab_reference
from app.adaptive.rules import get_rules
from app.dashboard.service import ACTIVITY_DAYS, Dashboard, dashboard
from app.db.models import (
    KCEvidence,
    LLMUsage,
    PlacementSession,
    ReviewLog,
    SkillEstimate,
    Tenant,
    User,
    UserCard,
    UserProfile,
    UserWordBook,
    Word,
)
from tests.integration.test_chat_send import login
from tests.integration.test_learner_api import switch_to

RULES = get_rules()
CATALOG = get_grammar_catalog()
UTC_ZONE = ZoneInfo("UTC")
SHANGHAI = ZoneInfo("Asia/Shanghai")
# 12:00 in Shanghai on 2026-09-30.
NOW = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)

THIRD_PERSON = "g.present_simple_third_person"  # A1
ARTICLES = "g.articles_basic"  # A1
PAST = "g.past_simple_irregular"


async def new_user(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = Tenant(name="t", kind="personal")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add_all([tenant, user])
    await session.flush()
    return user.id, tenant.id


async def board(session: AsyncSession, user_id: uuid.UUID, tz: ZoneInfo = UTC_ZONE) -> Dashboard:
    return await dashboard(session, user_id, rules=RULES, catalog=CATALOG, tz=tz, now=NOW)


async def test_a_new_learner_gets_empty_sections(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)

    b = await board(db_session, user_id)

    s = b.summary
    assert (s.cefr, s.vocab_size, s.vocab_cefr, s.vocab_reliable) == (None, None, None, None)
    assert (s.streak_days, s.studied_today, s.reviews_due) == (0, False, 0)
    assert b.book is None and b.skills == [] and b.errors == []
    assert all(level.unseen == level.total > 0 for level in b.grammar.values())
    assert sum(level.total for level in b.grammar.values()) == len(CATALOG.kcs)
    assert len(b.days) == ACTIVITY_DAYS
    assert b.days[-1].day == NOW.date() and b.days[0].day == NOW.date() - timedelta(days=83)
    assert all(d.reviews == d.turns == 0 for d in b.days)


async def test_book_words_split_by_progress(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)
    words = [Word(word=f"w{i}", translation="释义", tags=["cet4"], frq=i) for i in range(7)]
    other = Word(word="gre1", translation="释义", tags=["gre"], frq=1)
    db_session.add_all([*words, other])
    db_session.add(UserWordBook(user_id=user_id, book_id="cet4"))
    await db_session.flush()

    def card(
        word: Word, status: str, state: int | None = None, stability: float | None = None
    ) -> UserCard:
        return UserCard(
            user_id=user_id,
            word_id=word.id,
            source="book",
            status=status,
            state=state,
            stability=stability,
            due=NOW if status == "learning" else None,
        )

    db_session.add_all(
        [
            card(words[0], "learning", 2, 30.0),  # mastered
            card(words[1], "learning", 2, 21.0),  # mastered, at the threshold
            card(words[2], "learning", 2, 5.0),  # learning: stability too low
            card(words[3], "learning", 3, 40.0),  # learning: relearning a lapse
            card(words[4], "known"),
            card(words[5], "new"),  # own list, not started: unlearned
            card(other, "learning", 2, 50.0),  # another book
        ]
    )
    await db_session.flush()

    b = await board(db_session, user_id)

    assert b.book is not None and b.book.book.id == "cet4"
    split = (b.book.total, b.book.mastered, b.book.learning, b.book.known, b.book.unlearned)
    assert split == (7, 2, 2, 1, 2)


async def test_days_streak_and_chat_turns_follow_the_learners_calendar(
    db_session: AsyncSession,
) -> None:
    user_id, tenant_id = await new_user(db_session)
    someone, _ = await new_user(db_session)
    word = Word(word="w", translation="释义", tags=[], frq=1)
    db_session.add(word)
    await db_session.flush()
    card = UserCard(user_id=user_id, word_id=word.id, source="manual", status="new")
    db_session.add(card)
    await db_session.flush()

    def review(at: datetime) -> ReviewLog:
        return ReviewLog(
            card_id=card.id,
            user_id=user_id,
            rating=3,
            reviewed_at=at,
            card_before={},
            card_after={},
        )

    def usage(
        at: datetime, user: uuid.UUID = user_id, task: str = "chat", status: str = "ok"
    ) -> LLMUsage:
        return LLMUsage(
            tenant_id=tenant_id,
            user_id=user,
            task=task,
            connection_name="c",
            model="m",
            latency_ms=1,
            status=status,
            created_at=at,
        )

    db_session.add_all(
        [
            # 2026-09-29 20:00 UTC = 2026-09-30 04:00 in Shanghai: today there.
            review(datetime(2026, 9, 29, 20, 0, tzinfo=UTC)),
            review(datetime(2026, 9, 29, 21, 0, tzinfo=UTC)),
            # 2026-09-29 in Shanghai: a chat turn with an image, and a failed call.
            usage(datetime(2026, 9, 29, 3, 0, tzinfo=UTC), task="vision"),
            usage(datetime(2026, 9, 29, 3, 1, tzinfo=UTC), status="error"),
            # 2026-09-28 in Shanghai: chat; background reflection doesn't count.
            usage(datetime(2026, 9, 28, 3, 0, tzinfo=UTC)),
            usage(datetime(2026, 9, 27, 3, 0, tzinfo=UTC), task="reflect"),
            # Someone else's turn.
            usage(datetime(2026, 9, 27, 3, 0, tzinfo=UTC), user=someone),
            # Long ago, a separate run: outside the heatmap, not in the streak.
            review(datetime(2026, 1, 1, 3, 0, tzinfo=UTC)),
        ]
    )
    await db_session.flush()

    b = await board(db_session, user_id, tz=SHANGHAI)

    by_day = {d.day.isoformat(): (d.reviews, d.turns) for d in b.days if d.reviews or d.turns}
    assert by_day == {"2026-09-30": (2, 0), "2026-09-29": (0, 1), "2026-09-28": (0, 1)}
    assert (b.summary.streak_days, b.summary.studied_today) == (3, True)

    # In UTC the two reviews fall on 09-29, and today (09-30) is not studied yet.
    b = await board(db_session, user_id)
    assert (b.summary.streak_days, b.summary.studied_today) == (2, False)


async def test_grammar_levels_and_common_mistakes(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)
    recent = NOW - timedelta(days=2)

    def evidence(
        kc_id: str, correct: bool, source: str = "chat", at: datetime = recent
    ) -> KCEvidence:
        return KCEvidence(
            user_id=user_id,
            kc_id=kc_id,
            correct=correct,
            evidence="production" if source == "chat" else "recognition",
            source=source,
            error_type=None if correct else "omission",
            severity=None if correct else "medium",
            created_at=at,
        )

    db_session.add_all(
        [
            *(evidence(THIRD_PERSON, False) for _ in range(3)),
            evidence(ARTICLES, False),
            # Placement answers and old mistakes are not "common mistakes".
            *(evidence(ARTICLES, False, source="placement") for _ in range(5)),
            evidence(PAST, False, at=NOW - timedelta(days=31)),
            *(evidence(PAST, True) for _ in range(12)),
            evidence("g.not_in_the_catalog", False),
        ]
    )
    await db_session.flush()
    await mastery.rebuild(db_session, user_id, rules=RULES, catalog=CATALOG)

    b = await board(db_session, user_id)

    assert [(e.kc.id, e.mistakes) for e in b.errors] == [(THIRD_PERSON, 3), (ARTICLES, 1)]
    a1 = b.grammar["A1"]
    assert a1.weak == 2 and a1.unseen == a1.total - 2
    past = CATALOG.get(PAST)
    assert past is not None
    level = b.grammar[past.cefr]
    assert level.mastered + level.learning == 1 and level.unseen == level.total - 1


async def test_skills_on_one_cefr_scale(db_session: AsyncSession) -> None:
    user_id, _ = await new_user(db_session)
    db_session.add_all(
        [
            UserProfile(user_id=user_id, cefr_level="B1"),
            SkillEstimate(user_id=user_id, skill="grammar", rating=-0.2, attempts=20),
            # Knows half the words at rank 4000.
            SkillEstimate(user_id=user_id, skill="vocab", rating=math.log(4000), attempts=40),
            PlacementSession(
                user_id=user_id,
                status="done",
                stage="grammar",
                seed=1,
                rules_version="x",
                result={
                    "cefr": "B1",
                    "vocab": {"size": 3100, "reference_cefr": "B1", "reliable": True},
                    "grammar": {},
                    "answers": {},
                },
                finished_at=NOW,
            ),
        ]
    )
    await db_session.flush()

    b = await board(db_session, user_id)

    assert (b.summary.cefr, b.summary.vocab_size, b.summary.vocab_cefr) == ("B1", 3100, "B1")
    skills = {p.skill: p for p in b.skills}
    # Halfway between the B1 (-0.8) and B2 (0.4) cuts.
    assert skills["grammar"].cefr == "B1"
    assert skills["grammar"].position is not None
    assert math.isclose(skills["grammar"].position, 2.5)
    vocab = skills["vocab"]
    assert vocab.cefr == "B1" and vocab.vocab_size == 3100 and vocab.reliable is True
    # The scale agrees with the level the test derives from the same estimate.
    level = vocab_reference(4000, RULES.placement.vocab)
    assert level is not None and vocab.position is not None
    assert CEFR_LEVELS[int(vocab.position)] == level


async def test_api_returns_only_the_learners_own_board(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client, "first@example.com")
    await login(client, "second@example.com")
    await switch_to(client, "first@example.com")
    empty = await client.get("/dashboard", params={"tz": "Asia/Shanghai"})
    assert empty.status_code == 200, empty.text
    body = empty.json()
    assert body["book"] is None and body["skills"] == [] and body["errors"] == []
    assert set(body["grammar"]) == {"A1", "A2", "B1", "B2", "C1", "C2"}
    assert len(body["days"]) == ACTIVITY_DAYS
    assert body["summary"]["streak_days"] == 0

    response = await client.put("/vocab/book", json={"book_id": "cet4"})
    assert response.status_code == 204, response.text
    assert (await client.get("/dashboard")).json()["book"]["id"] == "cet4"

    await switch_to(client, "second@example.com")
    assert (await client.get("/dashboard")).json()["book"] is None
