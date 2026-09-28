import os
from collections.abc import AsyncIterator

import pytest
from alembic import command
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import Connection, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

# Tests must never send traces or hit real model APIs.
os.environ["OTEL_TRACING_ENABLED"] = "false"
# langsmith is a transitive dependency of langchain-core; keep it inert even if a
# developer has LANGSMITH_* set in their shell.
os.environ["LANGSMITH_TRACING"] = "false"

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://lingo:lingo@localhost:5433/lingo_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 32
# Fixed, test-only keyring (32 zero bytes): never valid outside the test suite.
os.environ["CREDENTIALS_ENCRYPTION_KEYS"] = "test:" + "A" * 43 + "="

# Imported after the environment is prepared.
from app.agents.chat_graph import build_chat_graph  # noqa: E402
from app.attachments.handlers import default_handlers  # noqa: E402
from app.attachments.processor import AttachmentProcessor  # noqa: E402
from app.db.migrate import alembic_config, setup_checkpointer  # noqa: E402
from app.db.session import create_engine, create_sessionmaker  # noqa: E402
from app.db.urls import to_psycopg_conninfo  # noqa: E402
from app.main import create_app  # noqa: E402

BUSINESS_TABLES = (
    "attachments",
    "llm_usage",
    "tenant_model_routes",
    "provider_connections",
    "conversations",
    "tenant_members",
    "users",
    "tenants",
)

# LangGraph's tables (checkpoint_migrations is kept: it records the applied schema).
CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


def _assert_test_database(url: str) -> None:
    # Every test truncates tables; never let that hit a dev or prod database.
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        raise RuntimeError(f"refusing to run DB tests against {name!r}: name must end in _test")


def run_alembic(connection: Connection, revision: str, *, downgrade: bool = False) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    config.attributes["configure_logger"] = False
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


@pytest.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Engine on a freshly migrated test database (downgrade to base, then upgrade)."""
    _assert_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(run_alembic, "base", downgrade=True)
            await conn.run_sync(run_alembic, "head")
        # Same layout as production: LangGraph's tables live next to ours.
        await setup_checkpointer(TEST_DATABASE_URL)
    except OSError as exc:  # pragma: no cover - environment problem, not a test failure
        raise RuntimeError(
            "test database unreachable; start it with `docker compose up -d postgres`"
        ) from exc
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with create_sessionmaker(db_engine)() as session:
        yield session
    async with db_engine.begin() as conn:
        tables = ", ".join((*BUSINESS_TABLES, *CHECKPOINT_TABLES))
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
async def app(db_engine: AsyncEngine, db_session: AsyncSession) -> AsyncIterator[FastAPI]:
    """The app wired to the test DB (tables truncated after each test).

    ASGITransport doesn't run the lifespan, so app.state is set up here directly.
    """
    app = create_app()
    app.state.engine = db_engine
    app.state.sessionmaker = create_sessionmaker(db_engine)
    app.state.attachment_processor = AttachmentProcessor(app.state.sessionmaker, default_handlers())
    async with AsyncPostgresSaver.from_conn_string(
        to_psycopg_conninfo(TEST_DATABASE_URL)
    ) as checkpointer:
        app.state.chat_graph = build_chat_graph(checkpointer)
        yield app
        await app.state.attachment_processor.stop()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
