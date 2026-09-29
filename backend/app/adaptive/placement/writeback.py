"""Storing a finished placement test (P1 plan §6.2, ADR 0012 §3).

One transaction: the session row gets the result; the profile's CEFR level becomes the
overall level; skill_estimates get the grammar ability and the vocabulary fit; each
grammar answer becomes recognition evidence (source=placement) and every KC is
replayed, since a new level changes all priors; then item difficulties are
re-estimated from the final ability. Saving a session that is already done changes
nothing, so a re-run graph step is harmless.

Wrong answers carry no `original` / `correction`: the evidence page would otherwise
show the test's answers.
"""

import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.elo import guess_for, update_item
from app.adaptive.kc.catalog import GrammarCatalog
from app.adaptive.placement.flow import PlacementResult
from app.adaptive.placement.items import ItemBank
from app.adaptive.rules import Rules
from app.db.models import (
    KCEvidence,
    PlacementItemStat,
    PlacementSession,
    SkillEstimate,
    UserProfile,
)


class SessionNotFoundError(Exception):
    pass


async def _set_skill(
    session: AsyncSession, user_id: uuid.UUID, skill: str, rating: float, attempts: int
) -> None:
    await session.execute(
        insert(SkillEstimate)
        .values(user_id=user_id, skill=skill, rating=rating, attempts=attempts)
        .on_conflict_do_update(
            index_elements=["user_id", "skill"], set_={"rating": rating, "attempts": attempts}
        )
    )


async def _calibrate_items(
    session: AsyncSession, result: PlacementResult, bank: ItemBank, rules: Rules
) -> None:
    """Move each answered item's difficulty by its surprise at the final ability."""
    answers = [a for a in result["answers"]["grammar"] if bank.get(a["item_id"]) is not None]
    if not answers:
        return
    ids = sorted({a["item_id"] for a in answers})
    priors = {item_id: bank.get(item_id).difficulty for item_id in ids}  # type: ignore[union-attr]
    await session.execute(
        insert(PlacementItemStat)
        .values([{"item_id": i, "difficulty": priors[i], "attempts": 0} for i in ids])
        .on_conflict_do_nothing(index_elements=["item_id"])
    )
    # Locked in id order, so two tests finishing at once neither lose an update nor
    # deadlock.
    stats = {
        stat.item_id: stat
        for stat in await session.scalars(
            select(PlacementItemStat)
            .where(PlacementItemStat.item_id.in_(ids))
            .order_by(PlacementItemStat.item_id)
            .with_for_update()
        )
    }
    ability = result["grammar"]["ability"]
    guess = guess_for(bank.format, rules)
    for answer in answers:
        stat = stats[answer["item_id"]]
        stat.difficulty = update_item(
            stat.difficulty, ability, answer["correct"], stat.attempts, rules, guess
        )
        stat.attempts += 1


async def save_result(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    result: PlacementResult,
    rules: Rules,
    catalog: GrammarCatalog,
    bank: ItemBank,
) -> bool:
    """Store the result and commit; False when the session was already done."""
    placement = await session.get(PlacementSession, session_id, with_for_update=True)
    if placement is None or placement.user_id != user_id:
        raise SessionNotFoundError(session_id)
    if placement.status == "done":
        return False
    placement.status = "done"
    placement.stage = "grammar"
    placement.result = dict(result)
    placement.finished_at = datetime.now(UTC)

    profile = await session.get(UserProfile, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id, interests=[], manual_fields=[])
        session.add(profile)
    profile.cefr_level = result["cefr"]

    grammar, vocab = result["grammar"], result["vocab"]
    await _set_skill(session, user_id, "grammar", grammar["ability"], grammar["answered"])
    # Vocabulary has no logit scale: its rating is ln V, V being the rank at which the
    # learner knows half the words.
    await _set_skill(
        session, user_id, "vocab", math.log(max(vocab["half_known_rank"], 1)), vocab["answered"]
    )

    for answer in result["answers"]["grammar"]:
        item = bank.get(answer["item_id"])
        if item is None:
            continue
        wrong = not answer["correct"]
        session.add(
            KCEvidence(
                user_id=user_id,
                kc_id=item.kc,
                correct=answer["correct"],
                evidence="recognition",
                source="placement",
                error_type="wrong_choice" if wrong else None,
                severity="medium" if wrong else None,
            )
        )
    await session.flush()
    await mastery.rebuild(session, user_id, rules=rules, catalog=catalog)
    await _calibrate_items(session, result, bank, rules)
    await session.commit()
    return True
