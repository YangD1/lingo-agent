"""Syncing grammar.yaml into `kc_edges` (task 45.3, ADR 0022 §2)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.graph_sync import catalog_edges, sync_kc_edges
from app.adaptive.kc.catalog import GrammarCatalog, get_grammar_catalog
from app.db.models import KCEdge


def _kc(kc_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": kc_id,
        "name_en": kc_id,
        "name_zh": kc_id,
        "cefr": "A1",
        "description": f"Uses {kc_id}.",
    } | fields


def _catalog(*kcs: dict[str, Any]) -> GrammarCatalog:
    return GrammarCatalog.model_validate({"kcs": list(kcs)})


async def _edges(session: AsyncSession) -> set[tuple[str, str, str]]:
    rows = await session.execute(select(KCEdge.from_kc, KCEdge.to_kc, KCEdge.kind))
    return {(f, t, k) for f, t, k in rows}


def test_catalog_edges_point_to_prerequisites_and_pair_both_ways() -> None:
    catalog = _catalog(
        _kc("g.a", confusable_with=["g.c"]), _kc("g.b", prerequisites=["g.a"]), _kc("g.c")
    )
    assert catalog_edges(catalog) == {
        ("g.b", "g.a", "prerequisite"),
        ("g.a", "g.c", "confusable"),
        ("g.c", "g.a", "confusable"),
    }


async def test_sync_writes_then_skips_then_rewrites(db_session: AsyncSession) -> None:
    first = _catalog(
        _kc("g.a", confusable_with=["g.c"]), _kc("g.b", prerequisites=["g.a"]), _kc("g.c")
    )
    assert await sync_kc_edges(db_session, first) is True
    await db_session.commit()
    assert await _edges(db_session) == catalog_edges(first)

    assert await sync_kc_edges(db_session, first) is False

    # An edited catalog: one pair dropped, one prerequisite added.
    second = _catalog(
        _kc("g.a"), _kc("g.b", prerequisites=["g.a"]), _kc("g.c", prerequisites=["g.b"])
    )
    assert await sync_kc_edges(db_session, second) is True
    await db_session.commit()
    assert await _edges(db_session) == {
        ("g.b", "g.a", "prerequisite"),
        ("g.c", "g.b", "prerequisite"),
    }


async def test_shipped_catalog_syncs(db_session: AsyncSession) -> None:
    assert await sync_kc_edges(db_session) is True
    await db_session.commit()
    edges = await _edges(db_session)
    catalog = get_grammar_catalog()
    assert len(edges) == sum(len(k.prerequisites) for k in catalog.kcs) + 2 * len(
        catalog.confusable_pairs()
    )
    assert ("g.will_future", "g.going_to_future", "confusable") in edges
