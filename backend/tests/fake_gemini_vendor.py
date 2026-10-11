"""An in-process Gemini Live server, for adapter and relay tests.

It records what it was sent (and each connection's query string) and answers by a
script: `on(kind, replies)` makes it send `replies` whenever it receives a message whose
top-level key is `kind` (`realtimeInput`, `clientContent`, `toolResponse`). `setup` is
answered with `setupComplete`, unless `refuse` is set: then the connection is closed
with a reason, as Gemini does. Messages go out as binary frames, as Gemini sends them.
"""

import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

PATH = "/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"


@dataclass
class FakeGemini:
    url: str = ""
    received: list[dict[str, Any]] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    script: dict[str, list[list[dict[str, Any]]]] = field(default_factory=dict)
    refuse: bool = False
    connections: list[ServerConnection] = field(default_factory=list)

    def on(self, kind: str, *replies: dict[str, Any]) -> None:
        """Answer each `kind` received with `replies` (queued per occurrence; the last
        one repeats)."""
        self.script.setdefault(kind, []).append(list(replies))

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [m[kind] for m in self.received if kind in m]

    async def push(self, *messages: dict[str, Any]) -> None:
        """Send messages unprompted on the latest connection."""
        ws = self.connections[-1]
        for message in messages:
            await ws.send(json.dumps(message).encode())

    async def hang_up(self, index: int = 0) -> None:
        await self.connections[index].close(1000, "session over")

    async def _handle(self, ws: ServerConnection) -> None:
        self.connections.append(ws)
        self.queries.append(ws.request.path.partition("?")[2] if ws.request else "")
        seen: dict[str, int] = {}
        async for message in ws:
            payload = json.loads(message)
            self.received.append(payload)
            kind = next(iter(payload), "")
            if kind == "setup":
                if self.refuse:
                    await ws.close(1008, "API key not valid. Please pass a valid API key.")
                    return
                await ws.send(json.dumps({"setupComplete": {}}).encode())
            answers = self.script.get(kind)
            if answers:
                replies = answers[min(seen.get(kind, 0), len(answers) - 1)]
                seen[kind] = seen.get(kind, 0) + 1
                for reply in replies:
                    await ws.send(json.dumps(reply).encode())


@asynccontextmanager
async def fake_gemini() -> AsyncIterator[FakeGemini]:
    vendor = FakeGemini()
    async with serve(vendor._handle, "127.0.0.1", 0, compression=None) as server:
        port = server.sockets[0].getsockname()[1]
        vendor.url = f"ws://127.0.0.1:{port}{PATH}"
        yield vendor


def audio(data: bytes) -> dict[str, Any]:
    part = {
        "inlineData": {"mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(data).decode()}
    }
    return {"serverContent": {"modelTurn": {"parts": [part]}}}


def said(text: str) -> dict[str, Any]:
    return {"serverContent": {"outputTranscription": {"text": text}}}


def heard(text: str) -> dict[str, Any]:
    return {"serverContent": {"inputTranscription": {"text": text}}}


def turn_complete(prompt: int = 0, response: int = 0) -> dict[str, Any]:
    return {
        "serverContent": {"turnComplete": True},
        "usageMetadata": {
            "promptTokenCount": prompt,
            "responseTokenCount": response,
            "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": prompt // 2}],
            "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": response}],
        },
    }
