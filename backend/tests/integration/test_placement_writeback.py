"""Storing a finished placement test (P1 plan §6.2)."""

import math
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.placement import flow
from app.adaptive.placement.flow import PlacementResult
from app.adaptive.placement.items import get_item_bank
from app.adaptive.placement.writeback import SessionNotFoundError, save_result
from app.adaptive.rules import get_rules
from app.db.models import (
    KCEvidence,
    KCMastery,
    PlacementItemStat,
    PlacementSession,
    SkillEstimate,
    User,
    UserProfile,
)
from tests.unit.placement_fixtures import POOL

RULES = get_rules()
BANK = get_item_bank()
CATALOG = get_grammar_catalog()


def finished_result(seed: int) -> PlacementResult:
    """A whole test: knows words up to rank 5000, gets two grammar items in three right."""
    progress = flow.new_progress(seed)
    while (q := flow.next_question(progress, POOL, BANK, RULES)) is not None:
        if q["stage"] == "vocab":
            answer: flow.AnswerInput = {
                "question_id": q["id"],
                "yes": q["rank"] is not None and q["rank"] <= 5000,
            }
        else:
            item = BANK.get(q["item_id"])
            assert item is not None
            pick = item.answer if q["index"] % 3 else item.distractors[0]
            answer = {"question_id": q["id"], "choice": q["options"].index(pick)}
        progress = flow.record(progress, q, answer, BANK)
    return flow.summarize(progress, POOL, BANK, RULES)


async def new_session(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    placement = PlacementSession(
        user_id=user.id, status="in_progress", stage="vocab", seed=1, rules_version=RULES.version
    )
    db.add(placement)
    await db.commit()
    return user.id, placement.id


async def save(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, r: PlacementResult
) -> bool:
    return await save_result(
        db,
        user_id=user_id,
        session_id=session_id,
        result=r,
        rules=RULES,
        catalog=CATALOG,
        bank=BANK,
    )


async def test_stores_level_skills_evidence_and_mastery(db_session: AsyncSession) -> None:
    user_id, session_id = await new_session(db_session)
    result = finished_result(seed=21)
    assert await save(db_session, user_id, session_id, result)

    placement = await db_session.get(PlacementSession, session_id)
    assert placement is not None
    assert (placement.status, placement.finished_at is not None) == ("done", True)
    assert placement.result is not None and placement.result["cefr"] == result["cefr"]
    profile = await db_session.get(UserProfile, user_id)
    assert profile is not None and profile.cefr_level == result["cefr"]

    skills = {
        s.skill: s
        for s in await db_session.scalars(
            select(SkillEstimate).where(SkillEstimate.user_id == user_id)
        )
    }
    assert skills["grammar"].rating == pytest.approx(result["grammar"]["ability"])
    assert skills["grammar"].attempts == result["grammar"]["answered"]
    assert skills["vocab"].rating == pytest.approx(math.log(result["vocab"]["half_known_rank"]))

    evidence = list(
        await db_session.scalars(select(KCEvidence).where(KCEvidence.user_id == user_id))
    )
    answers = result["answers"]["grammar"]
    assert len(evidence) == len(answers)
    assert {e.source for e in evidence} == {"placement"}
    assert {e.evidence for e in evidence} == {"recognition"}
    wrong = [e for e in evidence if not e.correct]
    assert len(wrong) == sum(not a["correct"] for a in answers) > 0
    # The test's answers are not shown on the evidence page.
    assert all(e.error_type == "wrong_choice" and e.original is None for e in wrong)
    assert all(e.correction is None for e in wrong)

    kcs = {BANK.get(a["item_id"]).kc for a in answers}  # type: ignore[union-attr]
    rows = await db_session.scalars(select(KCMastery.kc_id).where(KCMastery.user_id == user_id))
    assert set(rows) == kcs


async def test_items_move_by_their_surprise(db_session: AsyncSession) -> None:
    user_id, session_id = await new_session(db_session)
    result = finished_result(seed=22)
    await save(db_session, user_id, session_id, result)
    stats = {s.item_id: s for s in await db_session.scalars(select(PlacementItemStat))}
    answers = result["answers"]["grammar"]
    assert set(stats) == {a["item_id"] for a in answers}
    for a in answers:
        stat, prior = stats[a["item_id"]], BANK.get(a["item_id"]).difficulty  # type: ignore[union-attr]
        assert stat.attempts == 1
        # Right answers make an item look easier, wrong ones harder.
        assert (stat.difficulty < prior) if a["correct"] else (stat.difficulty > prior)


async def test_saving_twice_changes_nothing(db_session: AsyncSession) -> None:
    user_id, session_id = await new_session(db_session)
    result = finished_result(seed=23)
    assert await save(db_session, user_id, session_id, result)
    assert not await save(db_session, user_id, session_id, result)
    count = await db_session.scalar(select(func.count()).select_from(KCEvidence))
    assert count == len(result["answers"]["grammar"])
    attempts = set(await db_session.scalars(select(PlacementItemStat.attempts)))
    assert attempts == {1}


async def test_a_second_test_adds_attempts(db_session: AsyncSession) -> None:
    first_user, first = await new_session(db_session)
    second_user, second = await new_session(db_session)
    r1, r2 = finished_result(seed=24), finished_result(seed=24)
    await save(db_session, first_user, first, r1)
    await save(db_session, second_user, second, r2)
    attempts = set(await db_session.scalars(select(PlacementItemStat.attempts)))
    assert attempts == {2}


async def test_someone_elses_session_is_not_found(db_session: AsyncSession) -> None:
    _, session_id = await new_session(db_session)
    other, _ = await new_session(db_session)
    with pytest.raises(SessionNotFoundError):
        await save(db_session, other, session_id, finished_result(seed=25))
