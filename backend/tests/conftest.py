import ipaddress
import os
from collections.abc import AsyncIterator, Iterator

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

# Ignore the developer's repo-root .env: its values (e.g. PROVIDER_ALLOW_PRIVATE_NETWORKS,
# APP_ENV, PROVIDERS_CONFIG) would otherwise change what the tests see.
from app.settings import Settings  # noqa: E402

Settings.model_config["env_file"] = None

# Imported after the environment is prepared.
from app.adaptive.exercise.worker import PracticeWorker  # noqa: E402
from app.adaptive.placement.words import DatabaseWords  # noqa: E402
from app.adaptive.rules import get_rules  # noqa: E402
from app.agents.chat_graph import build_chat_graph  # noqa: E402
from app.agents.exercise_graph import build_exercise_graph  # noqa: E402
from app.agents.placement_graph import build_placement_graph  # noqa: E402
from app.attachments.handlers import default_handlers  # noqa: E402
from app.attachments.processor import AttachmentProcessor  # noqa: E402
from app.db.migrate import alembic_config, setup_checkpointer  # noqa: E402
from app.db.session import create_engine, create_sessionmaker  # noqa: E402
from app.db.urls import to_psycopg_conninfo  # noqa: E402
from app.main import create_app  # noqa: E402
from app.memory.worker import ReflectionWorker  # noqa: E402
from app.placement.service import PlacementRuntime  # noqa: E402
from app.providers import net_guard  # noqa: E402
from app.scheduler.jobs import JOBS  # noqa: E402
from app.scheduler.service import Scheduler  # noqa: E402
from app.writing.worker import WritingWorker  # noqa: E402

BUSINESS_TABLES = (
    "user_background_prefs",
    "scheduler_runs",
    "writing_submissions",
    "placement_item_stats",
    "placement_sessions",
    "review_logs",
    "user_cards",
    "user_word_book",
    "kc_evidence",
    "kc_mastery",
    "skill_estimates",
    "memories",
    "user_profiles",
    "attachments",
    "llm_usage",
    "tenant_model_routes",
    "provider_connections",
    "conversations",
    "tenant_members",
    "users",
    "tenants",
    "words",
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


@pytest.fixture(autouse=True)
def public_dns() -> Iterator[None]:
    """Hostnames resolve to a public address without real DNS: results would otherwise
    depend on the machine (a fake-ip proxy answers with private addresses, and CI may
    have no DNS at all). IP literals resolve to themselves. Modules that need other
    answers patch `net_guard.resolve` again in their own fixtures, which run later.
    Deliberately not built on `monkeypatch`: requesting it here would set it up before
    every module's fixtures and so undo module patches only after their teardowns ran."""

    async def fake_resolve(host: str, port: int) -> list[net_guard.IPAddress]:
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            return [ipaddress.ip_address("93.184.216.34")]

    real = net_guard.resolve
    net_guard.resolve = fake_resolve
    yield
    net_guard.resolve = real


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
        app.state.placement = PlacementRuntime(
            graph=build_placement_graph(checkpointer),
            checkpointer=checkpointer,
            sessionmaker=app.state.sessionmaker,
            words=DatabaseWords(app.state.sessionmaker, get_rules().placement.vocab),
        )
        # Off by default: most tests' fake models can't do structured output, and would
        # add llm_usage rows. Reflection tests switch it on (`enabled = True`).
        app.state.reflection_worker = ReflectionWorker(
            app.state.sessionmaker, app.state.chat_graph, enabled=False
        )
        # Without a model configured, sets come from the placement bank (Q33d).
        # Generating the next set ahead is off unless a test switches it on.
        app.state.practice_worker = PracticeWorker(
            app.state.sessionmaker, build_exercise_graph(), prefetch_enabled=False
        )
        # Without a model configured, reviews fail; tests swap in a fake model.
        app.state.writing_worker = WritingWorker(app.state.sessionmaker)
        # Not started: tests run jobs themselves.
        app.state.scheduler = Scheduler(app.state.sessionmaker, JOBS)
        yield app
        await app.state.writing_worker.stop()
        await app.state.practice_worker.stop()
        await app.state.reflection_worker.stop()
        await app.state.attachment_processor.stop()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
