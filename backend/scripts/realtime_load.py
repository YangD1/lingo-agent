"""How much the realtime relay costs the backend (ADR 0030 §1, Q60i).

Runs a fake vendor and N browser-like callers against a backend started separately
(with PROVIDER_ALLOW_PRIVATE_NETWORKS=true, on a scratch database: each caller signs up
a learner of its own), and samples that backend's memory and CPU from /proc. Audio
flows both ways the whole time, 100 ms frames of PCM16 at 24 kHz, which is more than a
real call (people take turns): an upper bound.

    uv run python scripts/realtime_load.py --api http://127.0.0.1:8077 --pid <uvicorn pid>
"""

import argparse
import asyncio
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve

RATE = 24_000  # an OpenAI-style connection on an unknown host: 24 kHz both ways
FRAME_SECONDS = 0.1
FRAME = b"\x01\x00" * int(RATE * FRAME_SECONDS)
REPLY_EVERY = 50  # frames between usage reports: a reply every 5 s
PAGE = os.sysconf("SC_PAGE_SIZE")
TICKS = os.sysconf("SC_CLK_TCK")


async def vendor(ws: ServerConnection) -> None:
    """Accepts the session, echoes each audio frame back as the tutor's voice and
    reports usage every few seconds."""
    frames = 0
    delta = base64.b64encode(FRAME).decode("ascii")
    async for message in ws:
        kind = json.loads(message).get("type")
        if kind == "session.update":
            await ws.send(json.dumps({"type": "session.updated", "session": {}}))
        elif kind == "input_audio_buffer.append":
            frames += 1
            await ws.send(
                json.dumps({"type": "response.output_audio.delta", "item_id": "i", "delta": delta})
            )
            if frames % REPLY_EVERY == 0:
                usage = {"input_tokens": 3000, "output_tokens": 100}
                await ws.send(
                    json.dumps(
                        {
                            "type": "response.done",
                            "response": {"status": "completed", "usage": usage},
                        }
                    )
                )


@dataclass
class Sample:
    rss_mb: float
    cpu_seconds: float


def sample(pid: int) -> Sample:
    with open(f"/proc/{pid}/statm") as f:
        rss_pages = int(f.read().split()[1])
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    # utime and stime are fields 14 and 15 of stat; [0] here is field 3.
    cpu = (int(fields[11]) + int(fields[12])) / TICKS
    return Sample(rss_pages * PAGE / 2**20, cpu)


@dataclass
class Caller:
    cookie: str
    sent: int = 0
    received: int = 0
    events: list[str] = field(default_factory=list)


async def sign_up(api: str, vendor_url: str) -> Caller:
    async with httpx.AsyncClient(base_url=api) as client:
        email = f"load-{uuid.uuid4().hex[:10]}@example.com"
        r = await client.post("/auth/register", json={"email": email, "password": "password123"})
        r.raise_for_status()
        r = await client.post(
            "/tenant/connections",
            json={
                "name": "fake",
                "kind": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-load-test-000000",
                "params": {"realtime_url": vendor_url},
            },
        )
        r.raise_for_status()
        r = await client.put("/tenant/routes/realtime/default", json={"models": ["fake:m"]})
        r.raise_for_status()
        cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    return Caller(cookie)


async def call(api: str, caller: Caller, seconds: float, started: asyncio.Event) -> None:
    url = api.replace("http", "ws", 1) + "/speech/realtime"
    async with connect(url, additional_headers={"Cookie": caller.cookie}) as ws:
        ready = json.loads(await ws.recv())
        assert ready["type"] == "ready", ready
        await started.wait()

        async def listen() -> None:
            async for message in ws:
                if isinstance(message, bytes):
                    caller.received += 1
                else:
                    caller.events.append(json.loads(message).get("type", ""))

        listener = asyncio.create_task(listen())
        end = time.monotonic() + seconds
        next_frame = time.monotonic()
        while time.monotonic() < end:
            await ws.send(FRAME)
            caller.sent += 1
            next_frame += FRAME_SECONDS
            await asyncio.sleep(max(0.0, next_frame - time.monotonic()))
        await ws.send(json.dumps({"type": "end"}))
        await asyncio.wait_for(listener, 15)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--calls", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()

    async with serve(vendor, "127.0.0.1", 0, compression=None, max_size=None) as server:
        port = server.sockets[0].getsockname()[1]
        vendor_url = f"ws://127.0.0.1:{port}/v1/realtime"
        callers = [await sign_up(args.api, vendor_url) for _ in range(args.calls)]
        await asyncio.sleep(3)
        idle = sample(args.pid)

        started = asyncio.Event()
        tasks = [asyncio.create_task(call(args.api, c, args.seconds, started)) for c in callers]
        await asyncio.sleep(2)  # every call connected, before the clock starts
        connected = sample(args.pid)
        began, t0 = time.monotonic(), connected.cpu_seconds
        started.set()
        peak = connected.rss_mb
        while not all(t.done() for t in tasks):
            await asyncio.sleep(1)
            peak = max(peak, sample(args.pid).rss_mb)
        busy = sample(args.pid)
        elapsed = time.monotonic() - began
        for t in tasks:
            t.result()
        await asyncio.sleep(3)
        after = sample(args.pid)

    sent = sum(c.sent for c in callers)
    received = sum(c.received for c in callers)
    report: dict[str, Any] = {
        "calls": args.calls,
        "seconds": round(elapsed, 1),
        "rss_idle_mb": round(idle.rss_mb, 1),
        "rss_connected_mb": round(connected.rss_mb, 1),
        "rss_peak_mb": round(peak, 1),
        "rss_after_mb": round(after.rss_mb, 1),
        "rss_per_call_mb": round((peak - idle.rss_mb) / args.calls, 2),
        "cpu_percent_of_one_core": round(100 * (busy.cpu_seconds - t0) / elapsed, 1),
        "frames_up": sent,
        "frames_down": received,
        "audio_kib_per_second_each_way": round(len(FRAME) * sent / elapsed / 1024, 1),
        "ended": sorted({e for c in callers for e in c.events if e == "ended"}),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
