import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.agents.chat_graph import build_chat_graph
from app.api import auth, health, providers, usage
from app.credentials.crypto import get_keyring
from app.db.migrate import create_checkpointer_pool
from app.db.session import create_engine, create_sessionmaker
from app.observability import setup_tracing, shutdown_tracing
from app.providers.llm import get_providers_config
from app.settings import Settings, get_settings
from app.usage.recorder import set_usage_sink
from app.usage.writer import UsageWriter

logger = logging.getLogger(__name__)


def init_state(app: FastAPI, settings: Settings) -> None:
    """Create process-wide resources on app.state (also used directly by tests)."""
    app.state.engine = create_engine(settings.database_url)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail fast on invalid configuration before accepting traffic.
    settings = get_settings()
    get_keyring()  # refuse to start without valid credential encryption keys
    get_providers_config()  # refuse to start with an invalid providers.*.yaml
    tracer_provider = setup_tracing(settings)
    init_state(app, settings)
    # Checkpoint tables are created by `python -m app.db.migrate`, not at startup.
    checkpoint_pool = create_checkpointer_pool(
        settings.database_url, settings.checkpoint_pool_max_size
    )
    await checkpoint_pool.open()
    app.state.chat_graph = build_chat_graph(AsyncPostgresSaver(checkpoint_pool))
    usage_writer = UsageWriter(app.state.sessionmaker)
    usage_writer.start()
    set_usage_sink(usage_writer.submit)
    try:
        yield
    finally:
        set_usage_sink(None)
        try:
            async with asyncio.timeout(5):
                await usage_writer.stop()
        except TimeoutError:
            logger.warning("usage writer did not drain within 5s; remaining rows lost")
        await checkpoint_pool.close()
        await app.state.engine.dispose()
        shutdown_tracing(tracer_provider)


def create_app() -> FastAPI:
    app = FastAPI(title="lingo-agent", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(providers.router)
    app.include_router(usage.router)
    return app


app = create_app()
