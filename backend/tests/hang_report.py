"""Where a stuck test was stuck (task 105).

pytest-timeout dumps stacks to the xdist worker's stderr and then ends the worker, so
CI only shows "node down". And for an async test the thread stacks just show the event
loop idling. So a little before the timeout this writes every thread's stack and every
asyncio task's stack to `.pytest-hangs/<worker>.txt`, which CI prints when it fails.
"""

import asyncio
import faulthandler
import gc
import os
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import TextIO

import pytest

HANG_DIR = Path(__file__).resolve().parent.parent / ".pytest-hangs"
# How long before pytest-timeout ends the worker.
LEAD_SECONDS = 10.0


def running_loops() -> list[asyncio.AbstractEventLoop]:
    # The loop belongs to another thread; diagnostics only.
    return [
        o for o in gc.get_objects() if isinstance(o, asyncio.AbstractEventLoop) and o.is_running()
    ]


def write_task_stacks(loop: asyncio.AbstractEventLoop, out: TextIO) -> None:
    """Every task's stack, read on the loop itself (it is idle while a test awaits)."""
    done = threading.Event()

    def dump() -> None:
        try:
            for task in asyncio.all_tasks(loop):
                print(f"--- {task!r}", file=out)
                task.print_stack(file=out)
        finally:
            done.set()

    loop.call_soon_threadsafe(dump)
    if not done.wait(5):
        print("(the event loop itself is blocked: see the thread stacks above)", file=out)


def write_report(path: Path, test: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        print(f"===== {time.strftime('%H:%M:%S')} still running: {test}", file=out)
        out.flush()
        faulthandler.dump_traceback(file=out, all_threads=True)
        for loop in running_loops():
            write_task_stacks(loop, out)
        out.flush()


def report_path() -> Path:
    return HANG_DIR / f"{os.environ.get('PYTEST_XDIST_WORKER', 'main')}.txt"


def pytest_configure(config: pytest.Config) -> None:
    # Only this run's hangs.
    report_path().unlink(missing_ok=True)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    timeout = float(item.config.getini("timeout") or 0)
    marker = item.get_closest_marker("timeout")
    if marker and marker.args:
        timeout = float(marker.args[0])
    if timeout <= LEAD_SECONDS:
        return (yield)
    timer = threading.Timer(timeout - LEAD_SECONDS, write_report, (report_path(), item.nodeid))
    timer.daemon = True
    timer.start()
    try:
        return (yield)
    finally:
        timer.cancel()
