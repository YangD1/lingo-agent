"""wait_tasks: waiting for a worker's background tasks (task 106)."""

import asyncio

from app.background import wait_tasks


async def _noop() -> None:
    pass


async def test_a_done_task_still_listed_does_not_spin() -> None:
    # CI run 39145484942: the task had finished, its discard callback was still queued,
    # and `while tasks: await gather(*tasks)` spun without letting it run.
    tasks: set[asyncio.Task[None]] = set()
    task = asyncio.create_task(_noop())
    task.add_done_callback(tasks.discard)
    tasks.add(task)
    await asyncio.sleep(0)  # the task finishes; its discard is queued behind us
    assert task.done() and task in tasks

    async with asyncio.timeout(1):
        await wait_tasks(tasks)

    assert not tasks


async def test_waits_for_tasks_added_while_waiting() -> None:
    tasks: dict[str, asyncio.Task[None]] = {}
    second = asyncio.Event()

    async def first() -> None:
        tasks["second"] = asyncio.create_task(second.wait())
        await asyncio.sleep(0)
        second.set()

    tasks["first"] = asyncio.create_task(first())

    async with asyncio.timeout(1):
        await wait_tasks(tasks.values())

    assert all(t.done() for t in tasks.values())


async def test_a_task_cancelled_before_it_started_is_not_waited_for() -> None:
    # Its `finally` never runs, so a worker that removes it there keeps it listed.
    tasks: dict[str, asyncio.Task[None]] = {}

    async def run() -> None:
        try:
            await asyncio.sleep(10)
        finally:
            tasks.pop("job", None)

    tasks["job"] = asyncio.create_task(run())
    tasks["job"].cancel()

    async with asyncio.timeout(1):
        await wait_tasks(tasks.values())

    assert tasks["job"].cancelled()
