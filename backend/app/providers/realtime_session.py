"""One live voice session with a realtime vendor, in vendor-neutral terms (ADR 0030 §2).

The relay sends the learner's PCM16 audio, interruptions, instructions and tool results,
and reads `RealtimeEvent`s back; it never knows which protocol is spoken. Two adapters
implement `RealtimeSession`: `openai_realtime` (OpenAI, Qwen-Omni, StepFun) and
`gemini_live`; `open_session` picks one by the target's dialect.

    async with await open_session(target, instructions=..., tools=[]) as call:
        await call.send_audio(pcm)
        async for event in call.events():
            ...

Audio is only base64-wrapped and unwrapped by the adapters, never decoded or resampled
(ADR 0030 §1).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Protocol, Self
from urllib.parse import urlsplit

import anyio
from websockets.asyncio.client import ClientConnection, connect

from app.providers.net_guard import guarded_socket
from app.providers.realtime import RealtimeTarget
from app.settings import get_settings

# Waiting for the vendor to accept the session settings; Qwen drops audio sent before.
SESSION_TIMEOUT = 10.0
# A vendor message is an audio chunk or an event; a few hundred KB at most.
MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class RealtimeConnectError(Exception):
    """The vendor could not be reached or refused the session; the cause is chained."""


type Role = Literal["learner", "tutor"]


@dataclass(frozen=True)
class AudioOut:
    """A chunk of the tutor's speech: PCM16 mono at the target's output rate."""

    data: bytes


@dataclass(frozen=True)
class Subtitle:
    """Part of what someone said (`final=False`: more text follows), or all of it."""

    role: Role
    item_id: str
    text: str
    final: bool


@dataclass(frozen=True)
class SpeechStarted:
    """The learner started talking: the tutor's reply, if any, should stop playing."""


@dataclass(frozen=True)
class LearnerTurn:
    """The learner's speech became turn `item_id`; its subtitle may come later. Turns
    come in the conversation's order, which late subtitles don't (ADR 0030 §6)."""

    item_id: str


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # JSON text as the model wrote it: parse and validate before use


@dataclass(frozen=True)
class ToolCalls:
    """The calls of one reply, to run together: the results go back in one go and the
    tutor answers once (ADR 0013: calls may run in parallel). Comes after the reply's
    `ResponseDone`."""

    calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0


@dataclass(frozen=True)
class ResponseDone:
    """The tutor finished (or was stopped in) one reply."""

    status: str  # completed / cancelled / failed / incomplete, as the vendor says
    usage: Usage | None


@dataclass(frozen=True)
class VendorError:
    """The vendor reported an error; the session may still go on."""

    code: str
    message: str


type RealtimeEvent = (
    AudioOut | Subtitle | SpeechStarted | LearnerTurn | ToolCalls | ResponseDone | VendorError
)


class RealtimeSession(Protocol):
    target: RealtimeTarget

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def close(self) -> None: ...

    async def send_audio(self, pcm: bytes) -> None:
        """PCM16 mono at the target's input rate."""
        ...

    async def interrupt(self, played_ms: int | None = None) -> None:
        """Stop the reply in progress. With `played_ms`, a vendor that can (OpenAI) also
        forgets the part the learner never heard."""
        ...

    async def respond(self, instructions: str | None = None) -> None:
        """Ask for a reply now; `instructions` are for this reply only (the wrap-up
        before the time limit, ADR 0030 §5)."""
        ...

    async def send_tool_results(
        self, results: list[tuple[str, str]], *, respond: bool = True
    ) -> None:
        """Give the model the results (`call_id`, output) of one `ToolCalls` and, unless
        told not to, let it go on talking (ADR 0013)."""
        ...

    def events(self) -> AsyncIterator[RealtimeEvent]:
        """Until the vendor hangs up."""
        ...


async def connect_ws(url: str, headers: dict[str, str], wait: float) -> ClientConnection:
    """A WebSocket to the vendor, through the private-address check (never through an
    environment proxy, which would bypass it)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "wss" else 80)
    with anyio.fail_after(wait):
        sock = await guarded_socket(
            host, port, allow_private=get_settings().provider_allow_private_networks
        )
    return await connect(
        url,
        sock=sock,
        additional_headers=headers,
        proxy=None,
        # Base64 audio barely compresses; deflate would cost memory per call.
        compression=None,
        open_timeout=wait,
        max_size=MAX_MESSAGE_BYTES,
        user_agent_header=None,
    )


async def open_session(
    target: RealtimeTarget,
    *,
    instructions: str,
    tools: list[dict[str, Any]] | None = None,
) -> RealtimeSession:
    """Connect, send the session settings and wait until the vendor accepts them.
    `tools` are function tools as `{name, description, parameters}`. Raises
    `RealtimeConnectError`; the caller then tries the route's next target."""
    # Imported here: the adapters import this module's types.
    if target.dialect == "gemini":
        from app.providers.gemini_live import open_gemini_session

        return await open_gemini_session(target, instructions=instructions, tools=tools)
    from app.providers.openai_realtime import open_openai_session

    return await open_openai_session(target, instructions=instructions, tools=tools)
