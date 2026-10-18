"""Waiting for a worker's in-process background tasks (task 106)."""

import asyncio
from collections.abc import Collection
from typing import Any


async def wait_tasks(tasks: Collection[asyncio.Future[Any]]) -> None:
    """Wait until every task in `tasks` is done, including ones added meanwhile:
    `tasks` is the worker's own set or `dict.values()`, read again each time.

    Only unfinished tasks are awaited. A task can be done and still listed: until its
    done-callback removes it, or for good when it was cancelled before it started and
    so never ran the `finally` that removes it. `gather` over futures that are all
    done completes without yielding to the event loop, so `while tasks: await
    gather(*tasks)` would spin there forever, and the callback would never run.
    """
    while pending := [t for t in tasks if not t.done()]:
        await asyncio.gather(*pending, return_exceptions=True)
    # Let done-callbacks already queued remove their tasks before the caller looks.
    await asyncio.sleep(0)
