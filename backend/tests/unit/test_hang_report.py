import asyncio
from pathlib import Path

from tests.hang_report import write_report


async def test_report_shows_where_an_awaiting_test_is_stuck(tmp_path: Path) -> None:
    gate = asyncio.Event()

    async def waiting_for_the_attachment() -> None:
        await gate.wait()

    task = asyncio.create_task(waiting_for_the_attachment())
    await asyncio.sleep(0)
    report = tmp_path / "gw0.txt"
    try:
        # From another thread, as the timer does, while this loop sits in an await.
        await asyncio.to_thread(write_report, report, "tests/x.py::test_stuck")
    finally:
        gate.set()
        await task

    text = report.read_text()
    assert "still running: tests/x.py::test_stuck" in text
    assert "Current thread" in text or "Thread 0x" in text  # every thread's stack
    assert "waiting_for_the_attachment" in text  # the task's own await
