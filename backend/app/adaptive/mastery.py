"""Keeping kc_mastery in step with kc_evidence (ADR 0012 §2).

kc_mastery is a cache: each row is `bkt.replay` over the KC's evidence, stamped with
the rules version it was computed under. `refresh` recomputes the KCs whose evidence
changed; `ensure_current` rebuilds a learner whose rows predate the current rules.
"""

import uuid
from collections.abc import Iterable
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.bkt import Observation, prior, replay
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog
from app.adaptive.rules import Evidence, Rules, Severity
from app.db.models import KCEvidence, KCMastery, UserProfile


async def refresh(
    session: AsyncSession,
    user_id: uuid.UUID,
    kc_ids: Iterable[str],
    *,
    rules: Rules,
    catalog: GrammarCatalog,
) -> None:
    """Recompute these grammar KCs from their evidence; does not commit.

    A KC with no evidence left loses its row. Ids outside the grammar catalog (word
    KCs, retired ids) are skipped: words take their mastery from FSRS (ADR 0010 §2).
    """
    wanted = sorted({kc_id for kc_id in kc_ids if kc_id in catalog})
    if not wanted:
        return
    level = cast(
        CefrLevel | None,
        await session.scalar(select(UserProfile.cefr_level).where(UserProfile.user_id == user_id)),
    )
    rows = await session.scalars(
        select(KCEvidence)
        .where(KCEvidence.user_id == user_id, KCEvidence.kc_id.in_(wanted))
        .order_by(KCEvidence.created_at, KCEvidence.id)
    )
    history: dict[str, list[Observation]] = {kc_id: [] for kc_id in wanted}
    for row in rows:
        history[row.kc_id].append(
            Observation(
                correct=row.correct,
                evidence=cast(Evidence, row.evidence),
                at=row.created_at,
                turn=row.message_id,
                severity=cast(Severity | None, row.severity),
            )
        )
    empty = [kc_id for kc_id, observations in history.items() if not observations]
    if empty:
        await session.execute(
            delete(KCMastery).where(KCMastery.user_id == user_id, KCMastery.kc_id.in_(empty))
        )
    for kc_id, observations in history.items():
        if not observations:
            continue
        kc = catalog.get(kc_id)
        assert kc is not None  # filtered above
        result = replay(observations, prior(kc.cefr, level, rules), rules)
        values = {
            "p_mastery": result.p_mastery,
            "observations": result.observations,
            "recog_correct": result.recog_correct,
            "produce_correct": result.produce_correct,
            "last_evidence_at": result.last_evidence_at,
            "rules_version": rules.version,
        }
        await session.execute(
            insert(KCMastery)
            .values(user_id=user_id, kc_id=kc_id, kind="grammar", **values)
            .on_conflict_do_update(index_elements=["user_id", "kc_id"], set_=values)
        )


async def rebuild(
    session: AsyncSession, user_id: uuid.UUID, *, rules: Rules, catalog: GrammarCatalog
) -> None:
    """Recompute every KC the learner has evidence or a row for; does not commit.

    For rule changes and anything else that affects all KCs at once, such as a new
    CEFR level from placement changing the priors.
    """
    with_evidence = await session.scalars(
        select(KCEvidence.kc_id).where(KCEvidence.user_id == user_id).distinct()
    )
    with_rows = await session.scalars(select(KCMastery.kc_id).where(KCMastery.user_id == user_id))
    await refresh(session, user_id, {*with_evidence, *with_rows}, rules=rules, catalog=catalog)


async def ensure_current(
    session: AsyncSession, user_id: uuid.UUID, *, rules: Rules, catalog: GrammarCatalog
) -> bool:
    """Rebuild the learner if any row was computed under other rules; does not commit.

    Call before reading or updating a learner's mastery. Returns whether it rebuilt.
    """
    stale = await session.scalar(
        select(KCMastery.kc_id)
        .where(KCMastery.user_id == user_id, KCMastery.rules_version != rules.version)
        .limit(1)
    )
    if stale is None:
        return False
    await rebuild(session, user_id, rules=rules, catalog=catalog)
    return True
