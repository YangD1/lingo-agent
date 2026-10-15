"""Demo data: one account with about two weeks of learning behind it (task 72.3).

    cd backend && uv run python -m app.demo.seed [--password …] [--lang zh|en]
    docker compose exec backend python -m app.demo.seed

Creates `demo@lingo.example.com`, or deletes it with everything it owns and creates it again
(Q72f); no other account is read or changed. No model is called: what a model would
have written comes from `content.py`, and every number from the real engines (the
placement test's scoring, FSRS reviews, practice grading and BKT / Elo replay, the
diagnosis checks), each dated in the past (Q72e). There is no chat history: LangGraph
threads are left to a real model during the demo. Memories have no vectors; facts are
all given to the tutor anyway, and episodes fall back to the most recent.

The account has no model connection: add one in settings before the demo, or join a
main account that lends its models.
"""

import argparse
import asyncio
import random
import secrets
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive import mastery
from app.adaptive.diagnosis.checks import DiagnosisOut, RootCauseOut
from app.adaptive.diagnosis.service import run_diagnosis
from app.adaptive.exercise.answer import answer as answer_item
from app.adaptive.exercise.formats import parse_body, parse_response
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog, get_grammar_catalog
from app.adaptive.placement import flow
from app.adaptive.placement.items import ItemBank, get_item_bank
from app.adaptive.placement.words import load_pool
from app.adaptive.placement.writeback import save_result
from app.adaptive.rules import Rules, get_rules
from app.agents.exercise_graph import ModelReply, StructuredCall
from app.agents.reading_graph import RewriteResult
from app.auth.service import get_personal_tenant, register_user
from app.db.models import (
    Article,
    ArticleVersion,
    Conversation,
    Exercise,
    ExerciseSet,
    Feed,
    FeedSubscription,
    KCEvidence,
    PlacementSession,
    Tenant,
    User,
    Word,
)
from app.db.session import create_engine, create_sessionmaker
from app.db.urls import to_psycopg_conninfo
from app.demo import content
from app.demo.content import Lang
from app.memory.service import add_memory, update_profile
from app.services.reading import sessions as reading
from app.services.reading.drafts import Question
from app.services.reading.versions import reading_level
from app.services.reading.versions import save_result as save_version
from app.services.vocab import scheduler as vocab
from app.services.vocab.progress import choose_book
from app.settings import get_settings
from app.speaking import sessions as speaking
from app.speaking.scenarios import get_scenarios
from app.speaking.summary import SpeakingSummary
from app.speaking.summary import check as check_summary
from app.writing import service as writing
from app.writing.review import Review
from app.writing.review import check as check_review
from app.writing.text import sentences

DEMO_DOMAIN = "@lingo.example.com"
DEFAULT_EMAIL = f"demo{DEMO_DOMAIN}"
# One seed for every random choice, FSRS's interval fuzzing included: a second run
# gives the same numbers (only ids and the time it was run differ).
SEED = 72
BOOK = "oxford3000"
REVIEW_DAYS = 10  # yesterday back to this many days ago, so the streak is 10 (Q72e)
NEW_PER_DAY = 3
PLACEMENT_DAYS_AGO = 12
# The simulated learner's chance of a right answer by item level: about B1.
GRAMMAR_RIGHT: dict[CefrLevel, float] = {
    "A1": 0.95,
    "A2": 0.9,
    "B1": 0.7,
    "B2": 0.35,
    "C1": 0.15,
    "C2": 0.05,
}
KNOWN_RANK = 3500  # words up to this frequency rank are mostly known


class NotDemoEmailError(ValueError):
    """Only addresses under @lingo.example.com are reseeded, so no real account is wiped."""


@dataclass(frozen=True, slots=True)
class Seeded:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    password: str


async def remove(session: AsyncSession, checkpointer: BaseCheckpointSaver[str], email: str) -> bool:
    """Delete the demo account and everything it owns; commits. False if there was none.

    The user's rows cascade from `users`, the tenant's (conversations, memories,
    feeds…) from `tenants`; LangGraph threads are outside both, so they go first.
    """
    _check_email(email)
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        return False
    tenant = await get_personal_tenant(session, user.id)
    threads = await session.scalars(select(Conversation.id).where(Conversation.user_id == user.id))
    placements = await session.scalars(
        select(PlacementSession.id).where(PlacementSession.user_id == user.id)
    )
    for thread_id in [*threads, *placements]:
        await checkpointer.adelete_thread(str(thread_id))
    await session.delete(user)
    if tenant is not None:
        await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
    await session.commit()
    return True


async def seed(
    sessionmaker: async_sessionmaker[AsyncSession],
    checkpointer: BaseCheckpointSaver[str],
    *,
    email: str = DEFAULT_EMAIL,
    password: str | None = None,
    lang: Lang = "zh",
    now: datetime | None = None,
) -> Seeded:
    """Create the demo account afresh, its history ending `now`."""
    _check_email(email)
    now = now or datetime.now(UTC)
    password = password or secrets.token_urlsafe(12)
    rules, catalog, bank = get_rules(), get_grammar_catalog(), get_item_bank()
    state = random.getstate()
    random.seed(SEED)
    try:
        async with sessionmaker() as session:
            await remove(session, checkpointer, email)
            user = await register_user(
                session, email, password, display_name="Lin" if lang == "en" else "小林"
            )
            # A demo account opens straight onto its history, not the setup guide (ADR 0042).
            user.setup_completed_at = now
            tenant = await get_personal_tenant(session, user.id)
            assert tenant is not None  # register_user makes one
            await _profile(session, user.id, lang)
            await _placement(session, user.id, now, rules, catalog, bank)
            await _vocabulary(session, user.id, now, rules)
            await _chat_mistakes(session, user.id, now)
            await _practice(session, user.id, now, lang, rules, catalog)
            await _writing(session, user.id, now, lang, rules, catalog)
            await _reading(session, user.id, tenant.id, now, rules)
            await _speaking(session, user.id, tenant.id, now, lang, rules)
            for memory in content.MEMORIES:
                await add_memory(
                    session, tenant_id=tenant.id, user_id=user.id, kind="fact", content=memory(lang)
                )
            # Writing and speaking evidence was redated after it was written.
            await mastery.rebuild(session, user.id, rules=rules, catalog=catalog)
            await session.commit()
            user_id, tenant_id = user.id, tenant.id
        await _diagnosis(sessionmaker, user_id, tenant_id, now, lang, rules, catalog)
    finally:
        random.setstate(state)
    return Seeded(user_id, tenant_id, email.lower(), password)


def _check_email(email: str) -> None:
    if not email.lower().endswith(DEMO_DOMAIN):
        raise NotDemoEmailError(email)


def _ago(now: datetime, days: float, hours: float = 0) -> datetime:
    """`days` before `now`, at a time of day `hours` earlier still."""
    return now - timedelta(days=days, hours=hours)


async def _profile(session: AsyncSession, user_id: uuid.UUID, lang: Lang) -> None:
    p = content.PROFILE
    changes: dict[str, Any] = {
        "native_language": p["native_language"],
        "occupation": cast(content.Text, p["occupation"])(lang),
        "goal": cast(content.Text, p["goal"])(lang),
        "interests": [i(lang) for i in cast(list[content.Text], p["interests"])],
        "daily_minutes": p["daily_minutes"],
        "explanation_language": lang,
    }
    await update_profile(session, user_id, changes, by_learner=True)


async def _placement(
    session: AsyncSession,
    user_id: uuid.UUID,
    now: datetime,
    rules: Rules,
    catalog: GrammarCatalog,
    bank: ItemBank,
) -> None:
    """The real test, answered by a simulated learner around B1, scored by the test's
    own code. Its answers leave the shared item calibration alone."""
    pool = await load_pool(session, rules.placement.vocab)
    rng = random.Random(SEED)
    progress = flow.new_progress(SEED)
    while (question := flow.next_question(progress, pool, bank, rules)) is not None:
        reply: flow.AnswerInput = {"question_id": question["id"]}
        if question["stage"] == "vocab":
            rank = question.get("rank")
            reply["yes"] = rank is not None and (
                (rank <= KNOWN_RANK and rng.random() > 0.08) or rng.random() < 0.3
            )
        else:
            item = bank.get(question["item_id"])
            assert item is not None
            right = rng.random() < GRAMMAR_RIGHT[item.cefr]
            wanted = item.answer if right else item.distractors[0]
            reply["choice"] = question["options"].index(wanted)
        progress = flow.record(progress, question, reply, bank)
    result = flow.summarize(progress, pool, bank, rules)
    taken = _ago(now, PLACEMENT_DAYS_AGO, 3)
    placement = PlacementSession(
        user_id=user_id,
        status="in_progress",
        stage="vocab",
        seed=SEED,
        rules_version=rules.version,
        created_at=taken - timedelta(minutes=12),
    )
    session.add(placement)
    await session.flush()
    await save_result(
        session,
        user_id=user_id,
        session_id=placement.id,
        result=result,
        rules=rules,
        catalog=catalog,
        bank=bank,
        now=taken,
        calibrate=False,
    )


async def _vocabulary(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, rules: Rules
) -> None:
    """A word book, and each day's reviews: every word due, then a few new ones."""
    await choose_book(session, user_id, book_id=BOOK, daily_new=10)
    words = list(
        await session.scalars(
            select(Word.id)
            .where(Word.oxford.is_(True))
            .order_by(Word.frq.asc().nulls_last(), Word.id)
            .limit(NEW_PER_DAY * REVIEW_DAYS)
        )
    )
    rng = random.Random(SEED)
    due: dict[int, datetime] = {}
    for days in range(REVIEW_DAYS, 0, -1):
        # Exactly `days` before now, never earlier in the day: seeded just after
        # midnight, an earlier hour would move "yesterday" back a date and break the streak.
        start = _ago(now, days)
        fresh = words[:NEW_PER_DAY]
        words = words[NEW_PER_DAY:]
        soonest = [w for w, _ in sorted(due.items(), key=lambda kv: (kv[1], kv[0]))]
        today = [w for w in soonest if due[w] <= start]
        if not today and not fresh:
            # Nothing due and the words ran out (a small dictionary): review ahead, so
            # every day is a study day.
            today = soonest[:1]
        for minute, word_id in enumerate([*today, *fresh]):
            roll = rng.random()
            rating: vocab.Rating = 1 if roll < 0.1 else 2 if roll < 0.2 else 4 if roll > 0.95 else 3
            card = await vocab.review(
                session,
                user_id,
                word_id=word_id,
                rating=rating,
                rules=rules,
                now=start + timedelta(minutes=minute),
                duration_ms=2500 + int(rng.random() * 4000),
            )
            assert card.due is not None
            due[word_id] = card.due
    await session.commit()


async def _chat_mistakes(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    """What reflection would have tagged in past chats. The conversations themselves
    are not made (no threads), so the evidence points at none."""
    for number, (days, original, correction) in enumerate(content.CHAT_MISTAKES):
        session.add(
            KCEvidence(
                user_id=user_id,
                kc_id=content.WEAK,
                correct=False,
                evidence="production",
                source="chat",
                message_id=f"demo-chat-{number}",
                error_type="wrong_form",
                severity="medium",
                original=original,
                correction=correction,
                created_at=_ago(now, days, 2),
            )
        )
    await session.commit()


async def _practice(
    session: AsyncSession,
    user_id: uuid.UUID,
    now: datetime,
    lang: Lang,
    rules: Rules,
    catalog: GrammarCatalog,
) -> None:
    """Finished practice sets, each answer graded by the code that grades the
    learner's own (no model: the wrong answers are on code-graded formats)."""
    for days, items in content.practice_sets(lang):
        started = _ago(now, days, 5)
        exercise_set = ExerciseSet(
            user_id=user_id,
            origin="practice",
            status="ready",
            kc_plan=[
                {
                    "kc_id": kc_id,
                    "format": fmt,
                    "target_difficulty": _difficulty(kc_id, catalog, rules),
                    "role": "weak",
                }
                for kc_id, fmt, *_ in items
            ],
            rules_version=rules.version,
            created_at=started - timedelta(minutes=2),
        )
        session.add(exercise_set)
        await session.flush()
        exercises = []
        for position, (kc_id, fmt, body, key, _) in enumerate(items):
            parse_body(fmt, body, key)  # as the generator's output is checked
            exercise = Exercise(
                user_id=user_id,
                set_id=exercise_set.id,
                position=position,
                kc_id=kc_id,
                format=fmt,
                content=body,
                answer=key,
                difficulty=_difficulty(kc_id, catalog, rules),
                status="ok",
                model="demo",
            )
            session.add(exercise)
            exercises.append(exercise)
        await session.commit()
        for position, (exercise, item) in enumerate(zip(exercises, items, strict=True)):
            await answer_item(
                session,
                user_id,
                exercise.id,
                parse_response(item[1], item[4]),
                grade_call=None,
                rules=rules,
                catalog=catalog,
                latency_ms=9000 + position * 1500,
                now=started + timedelta(minutes=position + 1),
            )


def _difficulty(kc_id: str, catalog: GrammarCatalog, rules: Rules) -> float:
    kc = catalog.get(kc_id)
    assert kc is not None
    return rules.difficulty.cefr_anchor[kc.cefr]


async def _writing(
    session: AsyncSession,
    user_id: uuid.UUID,
    now: datetime,
    lang: Lang,
    rules: Rules,
    catalog: GrammarCatalog,
) -> None:
    """A reviewed piece of writing, through the same checks and evidence as a real one."""
    row = await writing.create(
        session, user_id, text=content.WRITING_TEXT, prompt=content.WRITING_PROMPT
    )
    parts = sentences(row.text)
    checked = check_review(Review.model_validate(content.writing_review(lang)), parts, catalog)
    await writing.save(session, row, checked, "demo", rules=rules, catalog=catalog)
    row.words = await writing.collect_words(session, user_id, checked.vocab)
    written = _ago(now, content.WRITING_DAYS_AGO, 3)
    row.created_at = written
    row.reviewed_at = written + timedelta(seconds=40)
    await session.execute(
        update(KCEvidence).where(KCEvidence.writing_id == row.id).values(created_at=written)
    )
    await session.commit()


async def _reading(
    session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID, now: datetime, rules: Rules
) -> None:
    """An article on a feed of the demo's own, rewritten at its level, read and quizzed.
    The feed is never fetched; deleting the tenant deletes it."""
    read = _ago(now, content.READING_DAYS_AGO, 6)
    feed = Feed(
        tenant_id=tenant_id,
        url="https://example.com/lingo-demo/feed.xml",
        title="Lingo demo",
        license="cc_by",
        created_by=user_id,
        next_fetch_at=now + timedelta(days=3650),
    )
    session.add(feed)
    await session.flush()
    session.add(FeedSubscription(user_id=user_id, feed_id=feed.id, subscribed=True))
    article = Article(
        feed_id=feed.id,
        guid="lingo-demo-trees",
        url="https://example.com/lingo-demo/trees",
        title=content.ARTICLE_TITLE,
        published_at=read - timedelta(hours=20),
        body=content.ARTICLE_BODY,
        summary_only=False,
        license="cc_by",
        word_count=len(content.ARTICLE_BODY.split()),
    )
    session.add(article)
    await session.flush()
    level = await reading_level(session, user_id, rules)
    version = ArticleVersion(
        tenant_id=tenant_id, article_id=article.id, level=level, status="generating"
    )
    session.add(version)
    await session.flush()
    rng = random.Random(SEED)
    questions, choices = [], []
    for position, (text, options, evidence) in enumerate(content.QUESTIONS, start=1):
        shown = rng.sample(list(options), k=len(options))
        right = shown.index(options[0])
        questions.append(Question(position, text, tuple(shown), right, evidence))
        # The last question answered wrong.
        choices.append(right if position < len(content.QUESTIONS) else (right + 1) % 4)
    result = RewriteResult(
        title=content.REWRITE_TITLE,
        paragraphs=list(content.REWRITE),
        questions=questions,
        rejected=[],
        model="demo",
        critic_model="demo",
    )
    await save_version(session, version.id, result, level=level, rules=rules, now=read)
    await session.commit()
    row = await reading.open_session(
        session, user_id, article.id, version_id=version.id, level=level, now=read
    )
    await reading.answer(session, row, choices, rules=rules, now=read + timedelta(minutes=7))


async def _speaking(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    now: datetime,
    lang: Lang,
    rules: Rules,
) -> None:
    """A finished speaking practice with its summary and speaking-ability step. The
    transcript itself is not kept (no thread), only the counts and the summary."""
    row = await speaking.start(
        session,
        tenant_id,
        user_id,
        content.SPEAKING_SCENARIO,
        locale="zh-CN" if lang == "zh" else "en",
    )
    began = _ago(now, content.SPEAKING_DAYS_AGO, 1)
    texts = [text for text, _ in content.SPEAKING_TURNS]
    for number, (text, seconds) in enumerate(content.SPEAKING_TURNS):
        await speaking.record_turn(session, row.conversation_id, text, seconds)
        if "I have" in text:
            session.add(
                KCEvidence(
                    user_id=user_id,
                    kc_id=content.WEAK,
                    correct=False,
                    evidence="production",
                    source="speaking",
                    conversation_id=row.conversation_id,
                    message_id=f"demo-speaking-{number}",
                    error_type="wrong_form",
                    severity="medium",
                    original=text,
                    correction=text.replace("I have ", "I "),
                    created_at=began + timedelta(minutes=number),
                )
            )
    await session.refresh(row)
    summary = SpeakingSummary.model_validate(content.speaking_summary(lang))
    row.summary = check_summary(summary, texts)
    row.intelligibility = summary.intelligibility
    row.status = "done"
    row.started_at = began
    row.ended_at = began + timedelta(minutes=6)
    await session.execute(
        update(Conversation)
        .where(Conversation.id == row.conversation_id)
        .values(created_at=began, updated_at=row.ended_at)
    )
    await speaking.move_ability(session, row, get_scenarios().get(content.SPEAKING_SCENARIO), rules)
    await session.commit()


async def _diagnosis(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    now: datetime,
    lang: Lang,
    rules: Rules,
    catalog: GrammarCatalog,
) -> None:
    """Yesterday's weekly diagnosis, run by the real service (context, checks, memory)
    with a scripted reply that cites the mistakes the context gave it."""
    words = content.diagnosis(lang)

    def calls(ctx: Any, config: RunnableConfig, task: str) -> StructuredCall:
        async def call(messages: Sequence[Any], schema: type[Any]) -> ModelReply:
            cited = _cited(str(messages[-1].content))
            cause = RootCauseOut(
                hypothesis=words["hypothesis"],
                kc_ids=[content.WEAK],
                evidence_ids=cited,
                confidence="high",
                suggestion=words["suggestion"],
            )
            return ModelReply(DiagnosisOut(root_causes=[cause]), "demo")

        return call

    outcome = await run_diagnosis(
        sessionmaker,
        user_id,
        tenant_id,
        "weekly",
        rules=rules,
        catalog=catalog,
        now=_ago(now, content.DIAGNOSIS_DAYS_AGO, 2),
        calls=calls,
    )
    if outcome.diagnosis_id is None:
        raise RuntimeError(f"the demo diagnosis was skipped: {outcome.skipped}")


def _cited(prompt: str) -> list[int]:
    """The evidence ids the diagnosis prompt lists (`- evidence <id> …`)."""
    return [int(line.split()[2]) for line in prompt.splitlines() if "- evidence " in line]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.demo.seed", description=__doc__)
    parser.add_argument(
        "--password", help="the demo's password; a random one is printed if left out"
    )
    parser.add_argument("--lang", choices=["zh", "en"], default="zh", help="explanation language")
    return parser


async def _main(argv: list[str] | None = None, out: Callable[[str], None] = print) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with AsyncPostgresSaver.from_conn_string(
            to_psycopg_conninfo(settings.database_url)
        ) as checkpointer:
            seeded = await seed(
                create_sessionmaker(engine),
                checkpointer,
                password=args.password,
                lang=cast(Lang, args.lang),
            )
    finally:
        await engine.dispose()
    out(f"demo account: {seeded.email}")
    if args.password is None:
        out(f"password: {seeded.password}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
