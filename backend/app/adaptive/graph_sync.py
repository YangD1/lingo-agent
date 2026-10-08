"""Sync the grammar graph from grammar.yaml into `kc_edges` (ADR 0022 §2).

The YAML is the source of truth; the table only exists so graph queries can join
learner data in SQL. The backend runs `sync_kc_edges` at startup, and `make kc-sync`
runs this module for databases no backend has started against.
"""

import asyncio
import sys

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import GrammarCatalog, get_grammar_catalog
from app.db.models import KCEdge
from app.db.session import create_engine, create_sessionmaker
from app.settings import get_settings

Edge = tuple[str, str, str]  # (from_kc, to_kc, kind)


def catalog_edges(catalog: GrammarCatalog) -> set[Edge]:
    edges = {(kc.id, pre, "prerequisite") for kc in catalog.kcs for pre in kc.prerequisites}
    for a, b in catalog.confusable_pairs():
        edges |= {(a, b, "confusable"), (b, a, "confusable")}
    return edges


async def sync_kc_edges(session: AsyncSession, catalog: GrammarCatalog | None = None) -> bool:
    """Make `kc_edges` match the catalog; returns whether anything changed. Caller commits.

    Rewrites the whole table only when the edge sets differ, so an unchanged catalog
    costs one read per startup.
    """
    wanted = catalog_edges(catalog or get_grammar_catalog())
    rows = await session.execute(select(KCEdge.from_kc, KCEdge.to_kc, KCEdge.kind))
    if {(f, t, k) for f, t, k in rows} == wanted:
        return False
    await session.execute(delete(KCEdge))
    await session.execute(
        insert(KCEdge), [{"from_kc": f, "to_kc": t, "kind": k} for f, t, k in sorted(wanted)]
    )
    return True


async def _main() -> int:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_sessionmaker(engine)() as session:
            changed = await sync_kc_edges(session)
            await session.commit()
    finally:
        await engine.dispose()
    print("kc_edges updated" if changed else "kc_edges already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
