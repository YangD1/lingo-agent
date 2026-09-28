"""Bring the database fully up to date: `python -m app.db.migrate`.

Two schema owners, one entry point:
- Alembic owns the business tables (app/db/models.py).
- LangGraph's AsyncPostgresSaver owns its checkpoint tables and ships its own
  migrations, applied by `setup()`; they are deliberately kept out of Alembic.
"""

import asyncio
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.db.urls import to_psycopg_conninfo
from app.settings import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(ALEMBIC_INI)
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


def create_checkpointer_pool(database_url: str, max_size: int) -> AsyncConnectionPool[Any]:
    """Pool for AsyncPostgresSaver, opened by the caller (`await pool.open()`).

    The saver needs autocommit and dict rows; prepare_threshold=0 keeps it working
    behind transaction-pooling proxies such as PgBouncer.
    """
    return AsyncConnectionPool(
        to_psycopg_conninfo(database_url),
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        open=False,
    )


async def setup_checkpointer(database_url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(to_psycopg_conninfo(database_url)) as saver:
        await saver.setup()


def main() -> None:
    database_url = get_settings().database_url
    command.upgrade(alembic_config(database_url), "head")
    asyncio.run(setup_checkpointer(database_url))
    print("database is up to date")


if __name__ == "__main__":
    main()
