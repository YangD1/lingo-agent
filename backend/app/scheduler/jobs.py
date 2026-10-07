"""What a scheduled job is, and the jobs the backend runs (ADR 0025 §4).

Jobs are defined here in code and registered at startup; nothing about them is stored
except how each last went (`scheduler_runs`). A job works from "new since its last
success", so running it twice does no harm. Each one that calls a model also goes in
`app/usage/features.yaml` (timing: background) and `docs/agent-tools.md`.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from apscheduler.triggers.base import BaseTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True)
class JobContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    now: datetime
    # This run's id, for logs.
    run_id: uuid.UUID
    # When the job last succeeded; None before its first success.
    last_success_at: datetime | None


# Returns why the run did nothing (e.g. "budget_exhausted"), or None when it ran.
JobFunc = Callable[[JobContext], Awaitable[str | None]]


@dataclass(frozen=True)
class Job:
    name: str
    trigger: BaseTrigger
    run: JobFunc


# Filled in by the tasks that add jobs: RSS fetching first (task 41).
JOBS: tuple[Job, ...] = ()
