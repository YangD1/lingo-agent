import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.adaptive.exercise.worker import PracticeWorker
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.placement.items import get_item_bank
from app.adaptive.placement.words import DatabaseWords
from app.adaptive.rules import get_rules
from app.agents.chat_graph import build_chat_graph
from app.agents.exercise_graph import build_exercise_graph
from app.agents.placement_graph import build_placement_graph
from app.api import (
    activity,
    advice,
    attachments,
    auth,
    cards,
    chat,
    dashboard,
    health,
    learner,
    memory,
    placement,
    practice,
    providers,
    usage,
    vocab,
    writing,
)
from app.api.errors import install_error_handlers
from app.attachments.handlers import default_handlers
from app.attachments.processor import AttachmentProcessor, fail_interrupted
from app.chat.locks import ConversationLocks
from app.credentials.crypto import get_keyring
from app.db.migrate import create_checkpointer_pool
from app.db.session import create_engine, create_sessionmaker
from app.memory.worker import ReflectionWorker
from app.observability import setup_tracing, shutdown_tracing
from app.placement.service import PlacementRuntime
from app.providers.llm import get_providers_config
from app.scheduler.jobs import JOBS
from app.scheduler.service import Scheduler
from app.settings import Settings, get_settings
from app.usage.recorder import set_usage_sink
from app.usage.writer import UsageWriter
from app.writing.worker import WritingWorker

logger = logging.getLogger(__name__)


def init_state(app: FastAPI, settings: Settings) -> None:
    """Create process-wide resources on app.state (also used directly by tests)."""
    app.state.engine = create_engine(settings.database_url)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.attachment_processor = AttachmentProcessor(app.state.sessionmaker, default_handlers())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail fast on invalid configuration before accepting traffic.
    settings = get_settings()
    get_keyring()  # refuse to start without valid credential encryption keys
    get_providers_config()  # refuse to start with an invalid providers.*.yaml
    get_grammar_catalog()  # refuse to start with a broken grammar KC catalog
    get_rules()  # refuse to start with invalid adaptive rules
    get_item_bank()  # refuse to start with a broken placement item bank
    tracer_provider = setup_tracing(settings)
    init_state(app, settings)
    interrupted = await fail_interrupted(app.state.sessionmaker)
    if interrupted:
        logger.warning("%d attachments were mid-processing at the last shutdown", interrupted)
    # Checkpoint tables are created by `python -m app.db.migrate`, not at startup.
    checkpoint_pool = create_checkpointer_pool(
        settings.database_url, settings.checkpoint_pool_max_size
    )
    await checkpoint_pool.open()
    checkpointer = AsyncPostgresSaver(checkpoint_pool)
    app.state.chat_graph = build_chat_graph(checkpointer)
    app.state.placement = PlacementRuntime(
        graph=build_placement_graph(checkpointer),
        checkpointer=checkpointer,
        sessionmaker=app.state.sessionmaker,
        words=DatabaseWords(app.state.sessionmaker, get_rules().placement.vocab),
    )
    app.state.reflection_worker = ReflectionWorker(
        app.state.sessionmaker,
        app.state.chat_graph,
        enabled=settings.memory_reflection_enabled,
    )
    await app.state.reflection_worker.recover()
    app.state.practice_worker = PracticeWorker(app.state.sessionmaker, build_exercise_graph())
    interrupted = await app.state.practice_worker.recover()
    if interrupted:
        logger.warning("%d practice sets were mid-generation at the last shutdown", interrupted)
    app.state.writing_worker = WritingWorker(app.state.sessionmaker)
    interrupted = await app.state.writing_worker.recover()
    if interrupted:
        logger.warning("%d writing reviews were running at the last shutdown", interrupted)
    usage_writer = UsageWriter(app.state.sessionmaker)
    usage_writer.start()
    set_usage_sink(usage_writer.submit)
    app.state.scheduler = Scheduler(app.state.sessionmaker, JOBS)
    if settings.scheduler_enabled:
        await app.state.scheduler.start()
    try:
        yield
    finally:
        try:
            async with asyncio.timeout(5):
                # Cut-off runs are marked failed at the next start, then caught up.
                await app.state.scheduler.stop()
        except TimeoutError:
            logger.warning("scheduled jobs did not stop within 5s")
        try:
            async with asyncio.timeout(5):
                # Cursors live in the database: the next start picks up where this left.
                await app.state.reflection_worker.stop()
        except TimeoutError:
            logger.warning("reflection did not stop within 5s")
        try:
            async with asyncio.timeout(5):
                # Sets cut off here are marked failed; the learner just starts another.
                await app.state.practice_worker.stop()
        except TimeoutError:
            logger.warning("practice set generation did not stop within 5s")
        try:
            async with asyncio.timeout(5):
                # Reviews cut off here are marked failed; the learner submits again.
                await app.state.writing_worker.stop()
        except TimeoutError:
            logger.warning("writing review did not stop within 5s")
        try:
            async with asyncio.timeout(5):
                await app.state.attachment_processor.stop()
        except TimeoutError:
            logger.warning("attachment processing did not stop within 5s")
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
    app.state.conversation_locks = ConversationLocks()
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(providers.router)
    app.include_router(usage.router)
    app.include_router(chat.router)
    app.include_router(attachments.router)
    app.include_router(memory.router)
    app.include_router(activity.router)
    app.include_router(learner.router)
    app.include_router(vocab.router)
    app.include_router(placement.router)
    app.include_router(practice.router)
    app.include_router(dashboard.router)
    app.include_router(advice.router)
    app.include_router(cards.router)
    app.include_router(writing.router)
    return app


app = create_app()
