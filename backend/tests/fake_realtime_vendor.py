"""An in-process vendor speaking the OpenAI Realtime protocol, for adapter and relay tests.

It records what it was sent and answers by a script: `on(event_type, replies)` makes it
send `replies` (JSON events) whenever it receives that event type. Session settings are
accepted with `session.updated` unless `refuse` is set.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.server import ServerConnection, serve


@dataclass
class FakeVendor:
    url: str = ""
    received: list[dict[str, Any]] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)
    script: dict[str, list[list[dict[str, Any]]]] = field(default_factory=dict)
    refuse: bool = False
    connections: list[ServerConnection] = field(default_factory=list)

    def on(self, event_type: str, *replies: dict[str, Any]) -> None:
        """Answer each `event_type` received with `replies` (queued per occurrence: the
        first `on` answers the first such event, ...; the last one repeats)."""
        self.script.setdefault(event_type, []).append(list(replies))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.received if e.get("type") == event_type]

    async def push(self, *events: dict[str, Any]) -> None:
        """Send events unprompted to every open connection."""
        for ws in self.connections:
            for event in events:
                await ws.send(json.dumps(event))

    async def _handle(self, ws: ServerConnection) -> None:
        self.connections.append(ws)
        self.headers.append(dict(ws.request.headers) if ws.request else {})
        seen: dict[str, int] = {}
        async for message in ws:
            event = json.loads(message)
            self.received.append(event)
            kind = event.get("type", "")
            if kind == "session.update":
                if self.refuse:
                    await ws.send(json.dumps({"type": "error", "error": {"message": "bad key"}}))
                    await ws.close()
                    return
                await ws.send(json.dumps({"type": "session.updated", "session": {}}))
            answers = self.script.get(kind)
            if answers:
                replies = answers[min(seen.get(kind, 0), len(answers) - 1)]
                seen[kind] = seen.get(kind, 0) + 1
                for reply in replies:
                    await ws.send(json.dumps(reply))


@asynccontextmanager
async def fake_vendor(path: str = "/v1/realtime") -> AsyncIterator[FakeVendor]:
    vendor = FakeVendor()
    async with serve(vendor._handle, "127.0.0.1", 0, compression=None) as server:
        port = server.sockets[0].getsockname()[1]
        vendor.url = f"ws://127.0.0.1:{port}{path}"
        yield vendor
