from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.schema_filter import EXTERNALLY_MANAGED_TABLES, include_object
from tests.conftest import run_alembic


def _schema_diff(connection: Connection, *, filtered: bool = True) -> list[object]:
    opts = {"include_object": include_object} if filtered else {}
    context = MigrationContext.configure(connection, opts=opts)
    return list(compare_metadata(context, Base.metadata))


async def test_models_match_migrations(db_engine: AsyncEngine) -> None:
    """Fails when a model changes without a matching Alembic migration."""
    async with db_engine.connect() as conn:
        diff = await conn.run_sync(_schema_diff)
    assert diff == []


async def test_downgrade_and_upgrade_roundtrip(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.run_sync(run_alembic, "base", downgrade=True)
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        # Only Alembic's bookkeeping and LangGraph's own tables survive a full downgrade.
        assert set(tables) <= {"alembic_version", *EXTERNALLY_MANAGED_TABLES}
        await conn.run_sync(run_alembic, "head")
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert {"users", "tenants", "provider_connections", "llm_usage"} <= set(tables)


async def test_autogenerate_never_drops_langgraph_tables(db_engine: AsyncEngine) -> None:
    """Without the filter, autogenerate would emit DROP TABLE for checkpoint tables."""
    async with db_engine.connect() as conn:
        unfiltered = await conn.run_sync(lambda c: _schema_diff(c, filtered=False))
    dropped = {d[1].name for d in unfiltered if isinstance(d, tuple) and d[0] == "remove_table"}
    assert dropped == set(EXTERNALLY_MANAGED_TABLES)  # the tables exist, and are protected:
    async with db_engine.connect() as conn:
        assert await conn.run_sync(_schema_diff) == []
