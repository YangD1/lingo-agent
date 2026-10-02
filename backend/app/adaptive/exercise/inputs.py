"""What a practice set is planned and written from (ADR 0021 §2-§3).

`load` reads the learner's side from the database: the KC states `plan()` ranks, the
level and grammar ability it aims difficulty at, the learner's own wrong sentences for
`rewrite_own`, and the profile and a few remembered facts for personal context. `briefs` then turns
the plan into one brief per item, everything the generator needs for it.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.exercise.planner import KCState, PlannedItem, candidates, plan
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog, GrammarKC
from app.adaptive.rules import Rules
from app.db.models import Exercise, KCEvidence, KCMastery, SkillEstimate, UserProfile
from app.memory.service import facts_for_context, get_profile

# Remembered facts given to the generator (Q33f): the most recently updated ones. The
# generator picks what fits an item; the critic never sees them.
CONTEXT_FACTS = 8

type ExplainIn = Literal["zh", "en"]


@dataclass(frozen=True, slots=True)
class OwnSentence:
    """A sentence the learner got wrong in conversation, to rewrite (`rewrite_own`)."""

    evidence_id: int
    original: str
    correction: str | None


@dataclass(frozen=True, slots=True)
class LearnerInputs:
    level: CefrLevel | None
    # Grammar ability (Elo logits): the placement estimate, else the default level's
    # anchor, so an item of that level is answered half the time before guessing.
    ability: float
    # Every grammar KC with evidence; plan() adds the rest of the level window.
    states: Mapping[str, KCState]
    # Per KC, the best sentence to rewrite: never used in an item, else the one used
    # least, newest first.
    own_sentences: Mapping[str, OwnSentence]
    # Personal context for the generator: occupation, goal, exam, interests, and facts.
    profile: Mapping[str, str]
    facts: Sequence[str]
    # Language of explanations and of translate sources; Chinese unless set to English.
    explain_in: ExplainIn = "zh"


@dataclass(frozen=True, slots=True)
class ItemBrief:
    """One planned item with what the generator writes it from."""

    position: int
    item: PlannedItem
    kc: GrammarKC
    # Set for rewrite_own only.
    own_sentence: OwnSentence | None = None


async def _recent_mistakes(
    session: AsyncSession, user_id: uuid.UUID, *, rules: Rules, now: datetime
) -> dict[str, int]:
    """Counted mistakes per KC lately, from any source but placement (a test, not use)."""
    rows = await session.execute(
        select(KCEvidence.kc_id, func.count())
        .where(
            KCEvidence.user_id == user_id,
            KCEvidence.correct.is_(False),
            KCEvidence.source != "placement",
            KCEvidence.severity.in_(rules.evidence.counted_severities),
            KCEvidence.created_at >= now - timedelta(days=rules.practice.recent_mistake_days),
        )
        .group_by(KCEvidence.kc_id)
    )
    return {kc_id: count for kc_id, count in rows.all()}


async def _own_sentences(
    session: AsyncSession, user_id: uuid.UUID, *, rules: Rules, now: datetime
) -> dict[str, OwnSentence]:
    """Counted conversation mistakes with the learner's sentence, within
    `practice.rewrite_own_days`; per KC the one least used in earlier items."""
    used = (
        select(
            Exercise.content["evidence_id"].astext.cast(Integer).label("evidence_id"),
            func.count().label("times"),
        )
        .where(Exercise.user_id == user_id, Exercise.format == "rewrite_own")
        .group_by("evidence_id")
        .subquery()
    )
    times = func.coalesce(used.c.times, 0)
    rows = await session.execute(
        select(KCEvidence.kc_id, KCEvidence.id, KCEvidence.original, KCEvidence.correction)
        .outerjoin(used, used.c.evidence_id == KCEvidence.id)
        .where(
            KCEvidence.user_id == user_id,
            KCEvidence.correct.is_(False),
            KCEvidence.source == "chat",
            KCEvidence.severity.in_(rules.evidence.counted_severities),
            KCEvidence.original.is_not(None),
            func.length(func.trim(KCEvidence.original)) > 0,
            KCEvidence.created_at >= now - timedelta(days=rules.practice.rewrite_own_days),
        )
        .order_by(KCEvidence.kc_id, times, KCEvidence.created_at.desc(), KCEvidence.id.desc())
    )
    found: dict[str, OwnSentence] = {}
    for kc_id, evidence_id, original, correction in rows.all():
        if kc_id not in found:
            found[kc_id] = OwnSentence(evidence_id, cast(str, original).strip(), correction)
    return found


async def load(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
    now: datetime,
) -> LearnerInputs:
    """Everything about the learner a set is planned from; may rebuild stale mastery
    rows (`mastery.ensure_current`) but does not commit."""
    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    profile = await get_profile(session, user_id)
    level = cast(CefrLevel | None, profile.cefr_level if profile else None)
    rating = await session.scalar(
        select(SkillEstimate.rating).where(
            SkillEstimate.user_id == user_id, SkillEstimate.skill == "grammar"
        )
    )
    ability = (
        rating
        if rating is not None
        else rules.difficulty.cefr_anchor[level or rules.practice.default_level]
    )
    mistakes = await _recent_mistakes(session, user_id, rules=rules, now=now)
    own = {
        kc_id: s
        for kc_id, s in (await _own_sentences(session, user_id, rules=rules, now=now)).items()
        if kc_id in catalog
    }
    rows = await session.scalars(
        select(KCMastery).where(KCMastery.user_id == user_id, KCMastery.kind == "grammar")
    )
    states = {
        row.kc_id: KCState(
            p_mastery=row.p_mastery,
            formats_passed=frozenset(row.formats_passed),
            recent_mistakes=mistakes.get(row.kc_id, 0),
            has_own_sentence=row.kc_id in own,
            learned=row.mastered_at is not None,
            due=row.due,
        )
        for row in rows
        if row.kc_id in catalog
    }
    facts = [m.content for m in await facts_for_context(session, user_id, limit=CONTEXT_FACTS)]
    return LearnerInputs(
        level,
        ability,
        states,
        own,
        _personal(profile) if profile else {},
        facts,
        "en" if profile and profile.explanation_language == "en" else "zh",
    )


def _personal(profile: UserProfile) -> dict[str, str]:
    values = {
        "Occupation": profile.occupation,
        "Goal": profile.goal,
        "Target exam": profile.target_exam.upper() if profile.target_exam else None,
        "Interests": ", ".join(profile.interests) if profile.interests else None,
    }
    return {label: value for label, value in values.items() if value}


def plan_set(
    inputs: LearnerInputs,
    *,
    catalog: GrammarCatalog,
    rules: Rules,
    now: datetime,
    seed: int,
) -> list[PlannedItem]:
    return plan(
        catalog,
        inputs.states,
        learner_level=inputs.level,
        ability=inputs.ability,
        now=now,
        rules=rules,
        seed=seed,
    )


def wider_kcs(
    inputs: LearnerInputs, *, catalog: GrammarCatalog, rules: Rules, now: datetime
) -> list[str]:
    """The learner's candidate weak KCs by priority: bank stand-ins (Q33g)."""
    return candidates(catalog, inputs.states, learner_level=inputs.level, now=now, rules=rules).weak


def briefs(
    planned: Sequence[PlannedItem], inputs: LearnerInputs, catalog: GrammarCatalog
) -> list[ItemBrief]:
    """One brief per planned item, in set order. The planner only plans rewrite_own for
    KCs with an own sentence, so a missing one is a bug, not a case to handle."""
    out: list[ItemBrief] = []
    for position, item in enumerate(planned):
        kc = catalog.get(item.kc_id)
        assert kc is not None, item.kc_id
        own = inputs.own_sentences[item.kc_id] if item.format == "rewrite_own" else None
        out.append(ItemBrief(position, item, kc, own))
    return out
