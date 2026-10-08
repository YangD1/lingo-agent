"""Grammar graph queries (ADR 0022 §3).

Every read of `kc_edges` goes through this module, so the store can change (Apache AGE,
a graph database) without touching callers. `neighborhood` is the GraphRAG step of
diagnosis: from one KC to its prerequisite chain and confusable KCs, each with the
learner's mastery and latest mistakes. Turning that into prompt text is the caller's job.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive import mastery
from app.adaptive.kc.catalog import GrammarCatalog, GrammarKC
from app.adaptive.learner import MasteryState, mastery_state
from app.adaptive.rules import Rules
from app.db.models import KCEdge, KCEvidence, KCMastery

type Relation = Literal["target", "prerequisite", "confusable"]


@dataclass(frozen=True, slots=True)
class Mistake:
    evidence_id: int
    source: str
    error_type: str | None
    severity: str | None
    original: str | None
    correction: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GraphNode:
    kc: GrammarKC
    relation: Relation
    # Prerequisite steps from the target (0 for the target, 1 for confusables).
    depth: int
    # KCs in this neighborhood that list this one as a direct prerequisite.
    required_by: tuple[str, ...]
    # None when the learner has no evidence on the KC yet.
    mastery: KCMastery | None
    state: MasteryState | None
    # Newest first, at most rules.graph.mistakes_per_kc.
    mistakes: tuple[Mistake, ...]


@dataclass(frozen=True, slots=True)
class Neighborhood:
    target: GraphNode
    # Nearest first, then by id.
    prerequisites: list[GraphNode]
    # By id; a KC that is also in the prerequisite chain is listed there only.
    confusables: list[GraphNode]


async def prerequisite_chain(
    session: AsyncSession, kc_id: str, depth: int
) -> list[tuple[str, int]]:
    """KCs `kc_id` requires, up to `depth` steps away, as (kc_id, nearest step).

    A KC reached along several paths is listed once, at its shortest distance.
    """
    edges = KCEdge.__table__
    chain = (
        select(edges.c.to_kc.label("kc_id"), literal(1).label("depth"))
        .where(edges.c.from_kc == kc_id, edges.c.kind == "prerequisite")
        .cte("chain", recursive=True)
    )
    chain = chain.union_all(
        select(edges.c.to_kc, chain.c.depth + 1)
        .join(chain, edges.c.from_kc == chain.c.kc_id)
        .where(edges.c.kind == "prerequisite", chain.c.depth < depth)
    )
    nearest = func.min(chain.c.depth)
    rows = await session.execute(
        select(chain.c.kc_id, nearest).group_by(chain.c.kc_id).order_by(nearest, chain.c.kc_id)
    )
    return [(kc, step) for kc, step in rows]


async def confusables(session: AsyncSession, kc_id: str) -> list[str]:
    rows = await session.scalars(
        select(KCEdge.to_kc)
        .where(KCEdge.from_kc == kc_id, KCEdge.kind == "confusable")
        .order_by(KCEdge.to_kc)
    )
    return list(rows)


async def neighborhood(
    session: AsyncSession,
    user_id: uuid.UUID,
    kc_id: str,
    *,
    rules: Rules,
    catalog: GrammarCatalog,
) -> Neighborhood | None:
    """The KC, its prerequisite chain and its confusables, with the learner's data.

    None for a KC not in the catalog. May rebuild stale mastery rows first; the caller
    commits.
    """
    target = catalog.get(kc_id)
    if target is None:
        return None
    await mastery.ensure_current(session, user_id, rules=rules, catalog=catalog)
    chain = [
        (kc, step)
        for other, step in await prerequisite_chain(session, kc_id, rules.graph.prerequisite_depth)
        if (kc := catalog.get(other)) is not None
    ]
    in_chain = {kc.id for kc, _ in chain}
    mixed = [
        kc
        for other in await confusables(session, kc_id)
        if other not in in_chain and (kc := catalog.get(other)) is not None
    ]
    ids = [kc_id, *in_chain, *(kc.id for kc in mixed)]
    rows = {
        row.kc_id: row
        for row in await session.scalars(
            select(KCMastery).where(KCMastery.user_id == user_id, KCMastery.kc_id.in_(ids))
        )
    }
    mistakes = await _latest_mistakes(session, user_id, ids, rules.graph.mistakes_per_kc)
    # Which KCs here require which: the target and the chain are the only requirers.
    requirers = [target, *(kc for kc, _ in chain)]

    def node(kc: GrammarKC, relation: Relation, depth: int) -> GraphNode:
        row = rows.get(kc.id)
        return GraphNode(
            kc=kc,
            relation=relation,
            depth=depth,
            required_by=tuple(r.id for r in requirers if kc.id in r.prerequisites),
            mastery=row,
            state=mastery_state(row.p_mastery, rules) if row is not None else None,
            mistakes=tuple(mistakes.get(kc.id, ())),
        )

    return Neighborhood(
        target=node(target, "target", 0),
        prerequisites=[node(kc, "prerequisite", step) for kc, step in chain],
        confusables=[node(kc, "confusable", 1) for kc in mixed],
    )


async def _latest_mistakes(
    session: AsyncSession, user_id: uuid.UUID, kc_ids: list[str], limit: int
) -> dict[str, list[Mistake]]:
    if limit == 0:
        return {}
    rank = (
        func.row_number()
        .over(
            partition_by=KCEvidence.kc_id,
            order_by=(KCEvidence.created_at.desc(), KCEvidence.id.desc()),
        )
        .label("rank")
    )
    ranked = (
        select(KCEvidence, rank)
        .where(
            KCEvidence.user_id == user_id,
            KCEvidence.kc_id.in_(kc_ids),
            KCEvidence.correct.is_(False),
        )
        .subquery()
    )
    rows = await session.execute(
        select(ranked).where(ranked.c.rank <= limit).order_by(ranked.c.kc_id, ranked.c.rank)
    )
    found: dict[str, list[Mistake]] = {}
    for row in rows.mappings():
        found.setdefault(row["kc_id"], []).append(
            Mistake(
                evidence_id=row["id"],
                source=row["source"],
                error_type=row["error_type"],
                severity=row["severity"],
                original=row["original"],
                correction=row["correction"],
                created_at=row["created_at"],
            )
        )
    return found
