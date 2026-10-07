"""Runs the scheduled jobs and records how each went (ADR 0025 §1-3).

APScheduler only fires jobs: each firing starts a task here, so a run started by the
schedule and one started by the startup catch-up share the same rules. A job never
runs twice at once (a firing while it runs is dropped). At startup a job whose last
period was missed (or that never ran) runs once, not once per missed period.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import SchedulerRun
from app.scheduler.jobs import Job, JobContext

logger = logging.getLogger(__name__)

ERROR_MAX_CHARS = 500


def missed(trigger: BaseTrigger, last_finished_at: datetime | None, now: datetime) -> bool:
    """Whether the job was due at least once since it last finished."""
    if last_finished_at is None:
        return True
    due = trigger.get_next_fire_time(last_finished_at, now)
    return due is not None and due <= now


def describe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:ERROR_MAX_CHARS]


class Scheduler:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        jobs: Sequence[Job],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        names = [job.name for job in jobs]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate job names: {names}")
        self._sessionmaker = sessionmaker
        self._jobs = {job.name: job for job in jobs}
        self._clock = clock
        self._scheduler: AsyncIOScheduler | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self) -> None:
        """Schedule every job, then catch up the ones that missed a period."""
        await self._fail_interrupted()
        scheduler = AsyncIOScheduler(timezone=UTC)
        for job in self._jobs.values():
            # coalesce: a backlog of firings (e.g. after the machine slept) runs once.
            scheduler.add_job(self._fire, job.trigger, args=[job.name], id=job.name, coalesce=True)
        scheduler.start()
        self._scheduler = scheduler
        for name in await self._missed():
            logger.info("catching up scheduled job %s", name)
            self.trigger(name)

    async def stop(self) -> None:
        """Stop firing and cancel running jobs; their rows are fixed at the next start."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def trigger(self, name: str) -> bool:
        """Run a job now; False when it is already running."""
        job = self._jobs[name]
        if name in self._tasks:
            logger.info("scheduled job %s is still running; this firing is dropped", name)
            return False
        task = asyncio.create_task(self._run(job), name=f"scheduler-{name}")
        self._tasks[name] = task
        task.add_done_callback(lambda _: self._tasks.pop(name, None))
        return True

    async def wait(self, name: str) -> None:
        """Wait for a running job to finish (tests)."""
        task = self._tasks.get(name)
        if task is not None:
            await asyncio.shield(task)

    async def _fire(self, name: str) -> None:
        # A coroutine, so APScheduler calls it on the event loop rather than in a thread.
        self.trigger(name)

    async def _run(self, job: Job) -> None:
        started = self._clock()
        async with self._sessionmaker() as session:
            row = await session.get(SchedulerRun, job.name)
            if row is None:
                row = SchedulerRun(job=job.name, last_started_at=started, last_status="running")
                session.add(row)
            else:
                row.last_started_at = started
                row.last_status = "running"
            last_success_at = row.last_success_at
            await session.commit()
        ctx = JobContext(
            sessionmaker=self._sessionmaker,
            now=started,
            run_id=uuid.uuid4(),
            last_success_at=last_success_at,
        )
        skip_reason: str | None = None
        error: str | None = None
        try:
            skip_reason = await job.run(ctx)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("scheduled job %s failed", job.name)
            error = describe_error(exc)
        finished = self._clock()
        values: dict[str, object] = {
            "last_finished_at": finished,
            "last_skip_reason": skip_reason,
            "last_error": error,
        }
        if error is not None:
            values["last_status"] = "error"
        elif skip_reason is not None:
            values["last_status"] = "skipped"
        else:
            values["last_status"] = "ok"
            values["last_success_at"] = finished
        async with self._sessionmaker() as session:
            await session.execute(
                update(SchedulerRun).where(SchedulerRun.job == job.name).values(**values)
            )
            await session.commit()

    async def _fail_interrupted(self) -> None:
        """Runs still marked running were cut off by the last shutdown (one process)."""
        async with self._sessionmaker() as session:
            await session.execute(
                update(SchedulerRun)
                .where(SchedulerRun.last_status == "running")
                .values(last_status="error", last_error="interrupted by shutdown")
            )
            await session.commit()

    async def _missed(self) -> list[str]:
        async with self._sessionmaker() as session:
            rows = {
                row.job: row
                for row in await session.scalars(
                    select(SchedulerRun).where(SchedulerRun.job.in_(self._jobs))
                )
            }
        now = self._clock()
        return [
            name
            for name, job in self._jobs.items()
            if missed(job.trigger, row.last_finished_at if (row := rows.get(name)) else None, now)
        ]
