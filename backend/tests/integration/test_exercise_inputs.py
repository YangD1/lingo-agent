"""The learner side of a practice set: KC states, level, own sentences, facts (ADR 0021 §2)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.exercise import inputs
from app.adaptive.kc.catalog import CEFR_LEVELS, get_grammar_catalog
from app.adaptive.rules import get_rules
from app.auth.service import register_user
from app.db.models import (
    Exercise,
    ExerciseSet,
    KCEvidence,
    KCMastery,
    SkillEstimate,
    TenantMember,
    UserProfile,
)
from app.memory import service as memory

CATALOG, RULES = get_grammar_catalog(), get_rules()
NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
THIRD = "g.present_simple_third_person"  # A1
PERFECT = "g.present_perfect_experience"
PASSIVE = "g.passive_basic"


async def learner(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = await register_user(session, f"{uuid.uuid4()}@example.com", "password123")
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user.id)
    )
    assert tenant_id is not None
    return user.id, tenant_id


def mistake(
    user_id: uuid.UUID,
    kc_id: str,
    *,
    days_ago: float,
    source: str = "chat",
    severity: str = "medium",
    original: str | None = "He go to school.",
) -> KCEvidence:
    return KCEvidence(
        user_id=user_id,
        kc_id=kc_id,
        correct=False,
        evidence="production",
        source=source,
        format="cloze" if source == "exercise" else None,
        error_type="wrong_form",
        severity=severity,
        original=original,
        correction="He goes to school." if original else None,
        created_at=NOW - timedelta(days=days_ago),
    )


async def add(session: AsyncSession, user_id: uuid.UUID, *rows: KCEvidence) -> list[int]:
    session.add_all(rows)
    await session.flush()
    await mastery.refresh(session, user_id, {r.kc_id for r in rows}, rules=RULES, catalog=CATALOG)
    await session.flush()
    return [r.id for r in rows]


async def load(session: AsyncSession, user_id: uuid.UUID) -> inputs.LearnerInputs:
    return await inputs.load(session, user_id, rules=RULES, catalog=CATALOG, now=NOW)


async def test_new_learner_is_planned_at_the_default_level(db_session: AsyncSession) -> None:
    user_id, _ = await learner(db_session)

    found = await load(db_session, user_id)

    assert found.level is None
    assert found.ability == RULES.difficulty.cefr_anchor[RULES.practice.default_level]
    assert found.states == {} and found.own_sentences == {} and found.facts == []
    assert found.profile == {} and found.explain_in == "zh"
    planned = inputs.plan_set(found, catalog=CATALOG, rules=RULES, now=NOW, seed=1)
    assert len(planned) == RULES.practice.set_size
    default = CEFR_LEVELS.index(RULES.practice.default_level)
    for item in planned:
        kc = CATALOG.get(item.kc_id)
        assert kc is not None
        assert min(RULES.practice.importance_by_gap) <= default - CEFR_LEVELS.index(kc.cefr)
        assert item.format != "rewrite_own"  # nothing of their own to rewrite


async def test_placement_level_and_grammar_ability_are_used(db_session: AsyncSession) -> None:
    user_id, _ = await learner(db_session)
    db_session.add(
        UserProfile(
            user_id=user_id,
            cefr_level="B1",
            occupation="nurse",
            interests=["hiking", "jazz"],
            explanation_language="en",
        )
    )
    db_session.add(SkillEstimate(user_id=user_id, skill="grammar", rating=-0.3, attempts=20))
    await db_session.flush()

    found = await load(db_session, user_id)

    assert found.level == "B1"
    assert found.ability == -0.3
    assert found.profile == {"Occupation": "nurse", "Interests": "hiking, jazz"}
    assert found.explain_in == "en"


async def test_states_count_recent_mistakes_but_not_tests_or_minor_slips(
    db_session: AsyncSession,
) -> None:
    user_id, _ = await learner(db_session)
    await add(
        db_session,
        user_id,
        mistake(user_id, THIRD, days_ago=1),
        mistake(user_id, THIRD, days_ago=2, source="exercise", original=None),
        mistake(user_id, THIRD, days_ago=3, severity="low"),  # not counted
        mistake(user_id, THIRD, days_ago=40),  # too old
        mistake(user_id, PERFECT, days_ago=1, source="placement", original=None),
    )

    found = await load(db_session, user_id)

    assert found.states[THIRD].recent_mistakes == 2
    assert found.states[PERFECT].recent_mistakes == 0  # a test answer, not use
    assert found.states[THIRD].p_mastery < 0.5
    assert not found.states[THIRD].learned


async def test_learned_kcs_carry_their_due_date(db_session: AsyncSession) -> None:
    user_id, _ = await learner(db_session)
    await add(db_session, user_id, mistake(user_id, PASSIVE, days_ago=60))
    due = NOW + timedelta(days=3)
    await db_session.execute(
        update(KCMastery)
        .where(KCMastery.user_id == user_id)
        .values(mastered_at=NOW - timedelta(days=5), due=due, formats_passed=["cloze"])
    )

    state = (await load(db_session, user_id)).states[PASSIVE]

    assert state.learned and state.due == due
    assert state.formats_passed == frozenset({"cloze"})


async def test_own_sentence_prefers_one_not_rewritten_yet(db_session: AsyncSession) -> None:
    user_id, _ = await learner(db_session)
    used, fresh, _, _, _ = await add(
        db_session,
        user_id,
        mistake(user_id, THIRD, days_ago=1, original="She like tea."),
        mistake(user_id, THIRD, days_ago=5, original="He want it."),
        mistake(user_id, THIRD, days_ago=10, original="It work well."),
        mistake(user_id, THIRD, days_ago=0.5, severity="low", original="He say so."),
        mistake(user_id, THIRD, days_ago=45, original="She have one."),
    )
    exercise_set = ExerciseSet(user_id=user_id, origin="learner", status="done", kc_plan=[])
    db_session.add(exercise_set)
    await db_session.flush()
    db_session.add(
        Exercise(
            user_id=user_id,
            set_id=exercise_set.id,
            position=0,
            kc_id=THIRD,
            format="rewrite_own",
            content={"instruction": "Fix it.", "original": "She like tea.", "evidence_id": used},
            answer={},
            difficulty=0.0,
            status="ok",
        )
    )
    await db_session.flush()

    found = await load(db_session, user_id)

    own = found.own_sentences[THIRD]
    assert (own.evidence_id, own.original, own.correction) == (
        fresh,
        "He want it.",
        "He goes to school.",
    )
    assert found.states[THIRD].has_own_sentence


async def test_only_conversation_sentences_are_rewritten(db_session: AsyncSession) -> None:
    user_id, _ = await learner(db_session)
    await add(
        db_session,
        user_id,
        mistake(user_id, PERFECT, days_ago=1, source="placement"),
        mistake(user_id, PASSIVE, days_ago=1, original="  "),
    )

    found = await load(db_session, user_id)

    assert found.own_sentences == {}
    assert not found.states[PERFECT].has_own_sentence


async def test_facts_are_the_most_recent_few(db_session: AsyncSession) -> None:
    user_id, tenant_id = await learner(db_session)
    for i in range(inputs.CONTEXT_FACTS + 2):
        await memory.add_memory(
            db_session, tenant_id=tenant_id, user_id=user_id, kind="fact", content=f"Fact {i}"
        )
        await db_session.flush()

    facts = (await load(db_session, user_id)).facts

    assert len(facts) == inputs.CONTEXT_FACTS


async def test_briefs_give_rewrite_own_the_learner_sentence(db_session: AsyncSession) -> None:
    user_id, _ = await learner(db_session)
    db_session.add(UserProfile(user_id=user_id, cefr_level="A2"))
    await add(
        db_session,
        user_id,
        *(mistake(user_id, THIRD, days_ago=d, original="She like tea.") for d in (1, 2, 3)),
    )
    # Production formats come first from production_from_p on.
    await db_session.execute(
        update(KCMastery)
        .where(KCMastery.user_id == user_id)
        .values(p_mastery=RULES.practice.production_from_p)
    )
    found = await load(db_session, user_id)
    rewrite = next(
        (
            p
            for seed in range(200)
            for p in inputs.plan_set(found, catalog=CATALOG, rules=RULES, now=NOW, seed=seed)
            if p.format == "rewrite_own"
        ),
        None,
    )
    assert rewrite is not None

    (brief,) = inputs.briefs([rewrite], found, CATALOG)

    assert brief.kc.id == THIRD and brief.position == 0
    assert brief.own_sentence == found.own_sentences[THIRD]
    others = inputs.briefs(
        inputs.plan_set(found, catalog=CATALOG, rules=RULES, now=NOW, seed=1), found, CATALOG
    )
    assert [b.position for b in others] == list(range(len(others)))
    assert all((b.own_sentence is not None) == (b.item.format == "rewrite_own") for b in others)
