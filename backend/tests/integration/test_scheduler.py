"""Running scheduled jobs: run records, overlap, catch-up and shutdown (ADR 0025 §1-3)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import SchedulerRun
from app.db.session import create_sessionmaker
from app.scheduler.jobs import Job, JobContext
from app.scheduler.service import Scheduler

HOURLY = IntervalTrigger(hours=1, timezone=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
async def maker(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # db_session's teardown truncates the tables after the test.
    yield create_sessionmaker(db_engine)


async def run_row(maker: async_sessionmaker[AsyncSession], name: str) -> SchedulerRun | None:
    async with maker() as session:
        return await session.get(SchedulerRun, name)


class Recorder:
    """A job that records its contexts and does what it is told."""

    def __init__(self, *, skip: str | None = None, fail: bool = False) -> None:
        self.contexts: list[JobContext] = []
        self.skip = skip
        self.fail = fail
        self.release = asyncio.Event()
        self.release.set()
        self.ran = asyncio.Event()

    async def __call__(self, ctx: JobContext) -> str | None:
        self.contexts.append(ctx)
        self.ran.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("feed unreachable")
        return self.skip


async def test_success_is_recorded(maker: async_sessionmaker[AsyncSession]) -> None:
    clock = Clock()
    job = Recorder()
    scheduler = Scheduler(maker, [Job("fetch", HOURLY, job)], clock=clock)
    assert scheduler.trigger("fetch")
    await scheduler.wait("fetch")

    row = await run_row(maker, "fetch")
    assert row is not None
    assert row.last_status == "ok"
    assert row.last_success_at == clock.now
    assert job.contexts[0].last_success_at is None

    clock.now += timedelta(hours=1)
    scheduler.trigger("fetch")
    await scheduler.wait("fetch")
    # The next run sees when the previous one succeeded, to work from there.
    assert job.contexts[1].last_success_at == clock.now - timedelta(hours=1)


async def test_skip_and_error_keep_the_last_success(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    job = Recorder()
    scheduler = Scheduler(maker, [Job("fetch", HOURLY, job)], clock=clock)
    scheduler.trigger("fetch")
    await scheduler.wait("fetch")
    succeeded = clock.now

    clock.now += timedelta(hours=1)
    job.skip = "budget_exhausted"
    scheduler.trigger("fetch")
    await scheduler.wait("fetch")
    row = await run_row(maker, "fetch")
    assert row is not None
    assert (row.last_status, row.last_skip_reason) == ("skipped", "budget_exhausted")
    assert row.last_success_at == succeeded

    clock.now += timedelta(hours=1)
    job.skip, job.fail = None, True
    scheduler.trigger("fetch")
    await scheduler.wait("fetch")
    row = await run_row(maker, "fetch")
    assert row is not None
    assert row.last_status == "error"
    assert row.last_error == "RuntimeError: feed unreachable"
    assert row.last_skip_reason is None
    assert row.last_success_at == succeeded
    assert row.last_finished_at == clock.now


async def test_a_running_job_is_not_started_again(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    job = Recorder()
    job.release.clear()
    scheduler = Scheduler(maker, [Job("fetch", HOURLY, job)])
    assert scheduler.trigger("fetch")
    await asyncio.sleep(0.05)
    assert not scheduler.trigger("fetch")
    job.release.set()
    await scheduler.wait("fetch")
    assert len(job.contexts) == 1
    assert scheduler.trigger("fetch")
    await scheduler.wait("fetch")
    assert len(job.contexts) == 2


async def test_start_catches_up_missed_jobs_once(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    fresh, stale, never = Recorder(), Recorder(), Recorder()
    async with maker() as session:
        for name, finished in (
            ("fresh", clock.now - timedelta(minutes=10)),
            ("stale", clock.now - timedelta(days=2)),  # many periods: still one run
        ):
            session.add(
                SchedulerRun(
                    job=name,
                    last_started_at=finished,
                    last_finished_at=finished,
                    last_success_at=finished,
                    last_status="ok",
                )
            )
        await session.commit()
    scheduler = Scheduler(
        maker,
        [Job("fresh", HOURLY, fresh), Job("stale", HOURLY, stale), Job("never", HOURLY, never)],
        clock=clock,
    )
    await scheduler.start()
    try:
        await scheduler.wait("stale")
        await scheduler.wait("never")
        assert (len(fresh.contexts), len(stale.contexts), len(never.contexts)) == (0, 1, 1)
    finally:
        await scheduler.stop()


async def test_stop_cancels_and_next_start_repairs(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    job = Recorder()
    job.release.clear()
    scheduler = Scheduler(maker, [Job("fetch", HOURLY, job)], clock=clock)
    await scheduler.start()  # never ran: catches up, and hangs until stopped
    await asyncio.sleep(0.05)
    await scheduler.stop()
    row = await run_row(maker, "fetch")
    assert row is not None
    assert row.last_status == "running"

    job.release.set()
    restarted = Scheduler(maker, [Job("fetch", HOURLY, job)], clock=clock)
    await restarted.start()
    try:
        await restarted.wait("fetch")
    finally:
        await restarted.stop()
    # The cut-off run never finished, so the restart ran it again.
    assert len(job.contexts) == 2
    row = await run_row(maker, "fetch")
    assert row is not None
    assert row.last_status == "ok"


async def test_interrupted_runs_are_marked_failed(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    async with maker() as session:
        session.add(
            SchedulerRun(
                job="gone",  # no longer defined in code: only its row is fixed
                last_started_at=clock.now,
                last_status="running",
            )
        )
        await session.commit()
    scheduler = Scheduler(maker, [], clock=clock)
    await scheduler.start()
    await scheduler.stop()
    row = await run_row(maker, "gone")
    assert row is not None
    assert (row.last_status, row.last_error) == ("error", "interrupted by shutdown")


def test_duplicate_names_are_refused(maker: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Scheduler(maker, [Job("a", HOURLY, Recorder()), Job("a", HOURLY, Recorder())])


async def test_the_schedule_fires_jobs(maker: async_sessionmaker[AsyncSession]) -> None:
    job = Recorder()
    now = datetime.now(UTC)
    async with maker() as session:
        # Just ran: no catch-up, so any run comes from APScheduler.
        session.add(
            SchedulerRun(job="tick", last_started_at=now, last_finished_at=now, last_status="ok")
        )
        await session.commit()
    scheduler = Scheduler(maker, [Job("tick", IntervalTrigger(seconds=0.2, timezone=UTC), job)])
    await scheduler.start()
    try:
        async with asyncio.timeout(3):
            await job.ran.wait()
    finally:
        await scheduler.stop()
