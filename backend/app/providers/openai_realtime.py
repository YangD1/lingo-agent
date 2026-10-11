"""The `openai_realtime` adapter (ADR 0030 §2): one live voice session with a vendor that
speaks the OpenAI Realtime protocol, in either spelling (`ga` or `beta`, see
`app/providers/realtime.py`).

The relay talks to it in vendor-neutral terms: it sends the learner's PCM16 audio,
interruptions, instructions and tool results, and reads `RealtimeEvent`s back. Audio is
only base64-wrapped and unwrapped here, never decoded or resampled (ADR 0030 §1).

    async with await open_session(target, instructions=..., tools=[]) as call:
        await call.send_audio(pcm)
        async for event in call.events():
            ...

Vendor messages are untrusted: anything this module doesn't know is dropped, and what
it passes on is parsed defensively (a missing field is a skipped event, not a crash).
Both spellings of an event name are accepted whatever the dialect, since vendors
copying the protocol mix them.
"""

import base64
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import anyio
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.providers.net_guard import guarded_socket
from app.providers.realtime import RealtimeTarget, redact_key
from app.settings import get_settings

logger = logging.getLogger(__name__)

# Waiting for the vendor to accept the session settings; Qwen drops audio sent before.
SESSION_TIMEOUT = 10.0
# A vendor message is an audio chunk or an event; a few hundred KB at most.
MAX_MESSAGE_BYTES = 4 * 1024 * 1024

# Server-side voice activity detection (Q60d): the vendor decides when the learner is
# done, and stops talking when they start (barge-in).
_VAD: dict[str, Any] = {
    "type": "server_vad",
    "prefix_padding_ms": 300,
    "silence_duration_ms": 500,
}


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


@dataclass
class RealtimeSession:
    target: RealtimeTarget
    _ws: ClientConnection
    # The tutor's reply being spoken, for truncating it on interruption (ga only).
    _speaking_item: str | None = None
    _seen_calls: set[str] = field(default_factory=set)
    # Calls of the reply in progress, handed over when it is done.
    _calls: list[ToolCall] = field(default_factory=list)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close()

    async def send_audio(self, pcm: bytes) -> None:
        """PCM16 mono at the target's input rate."""
        await self._send(
            {"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()}
        )

    async def interrupt(self, played_ms: int | None = None) -> None:
        """Stop the reply in progress. With `played_ms`, a vendor that can (OpenAI) also
        forgets the part the learner never heard."""
        await self._send({"type": "response.cancel"})
        if self.target.dialect == "ga" and self._speaking_item and played_ms is not None:
            await self._send(
                {
                    "type": "conversation.item.truncate",
                    "item_id": self._speaking_item,
                    "content_index": 0,
                    "audio_end_ms": max(0, played_ms),
                }
            )
        self._speaking_item = None

    async def respond(self, instructions: str | None = None) -> None:
        """Ask for a reply now; `instructions` replace the session's for this reply only
        (the wrap-up before the time limit, ADR 0030 §5)."""
        event: dict[str, Any] = {"type": "response.create"}
        if instructions:
            event["response"] = {"instructions": instructions}
        await self._send(event)

    async def send_tool_results(
        self, results: list[tuple[str, str]], *, respond: bool = True
    ) -> None:
        """Give the model the results (`call_id`, output) of one `ToolCalls` and, unless
        told not to, let it go on talking (ADR 0013)."""
        for call_id, output in results:
            await self._send(
                {
                    "type": "conversation.item.create",
                    "item": {"type": "function_call_output", "call_id": call_id, "output": output},
                }
            )
        if respond:
            await self.respond()

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        """Until the vendor hangs up."""
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    continue  # the protocol is JSON text only
                try:
                    payload = json.loads(message)
                except ValueError:
                    continue
                if isinstance(payload, dict):
                    for event in self._translate(payload):
                        yield event
        except ConnectionClosed:
            return

    async def _send(self, event: dict[str, Any]) -> None:
        await self._ws.send(json.dumps(event))

    def _translate(self, payload: dict[str, Any]) -> list[RealtimeEvent]:
        kind = payload.get("type")
        match kind:
            case "response.output_audio.delta" | "response.audio.delta":
                delta = payload.get("delta")
                if not isinstance(delta, str):
                    return []
                if isinstance(item := payload.get("item_id"), str):
                    self._speaking_item = item
                try:
                    return [AudioOut(base64.b64decode(delta, validate=True))]
                except ValueError:
                    return []
            case "response.output_audio_transcript.delta" | "response.audio_transcript.delta":
                return _subtitle("tutor", payload, "delta", final=False)
            case "response.output_audio_transcript.done" | "response.audio_transcript.done":
                return _subtitle("tutor", payload, "transcript", final=True)
            case "conversation.item.input_audio_transcription.delta":
                # Qwen streams `text`; OpenAI and StepFun `delta`.
                key = "delta" if "delta" in payload else "text"
                return _subtitle("learner", payload, key, final=False)
            case "conversation.item.input_audio_transcription.completed":
                return _subtitle("learner", payload, "transcript", final=True)
            case "conversation.item.input_audio_transcription.failed":
                # Nothing more will come for this turn: it is done, with no text.
                return _subtitle("learner", {**payload, "transcript": ""}, "transcript", final=True)
            case "input_audio_buffer.speech_started":
                return [SpeechStarted()]
            case "input_audio_buffer.committed":
                item = payload.get("item_id")
                return [LearnerTurn(item)] if isinstance(item, str) else []
            case "response.function_call_arguments.done":
                return self._tool_call(payload)
            case "response.output_item.done":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") == "function_call":
                    return self._tool_call(item)
                return []
            case "response.done":
                response = payload.get("response")
                response = response if isinstance(response, dict) else {}
                self._speaking_item = None
                done: list[RealtimeEvent] = [
                    ResponseDone(str(response.get("status") or ""), _usage(response))
                ]
                if self._calls:
                    done.append(ToolCalls(tuple(self._calls)))
                    self._calls = []
                return done
            case "error":
                error = payload.get("error")
                error = error if isinstance(error, dict) else {}
                return [
                    VendorError(
                        str(error.get("code") or error.get("type") or "error")[:64],
                        str(error.get("message") or "")[:500],
                    )
                ]
        return []

    def _tool_call(self, payload: dict[str, Any]) -> list[RealtimeEvent]:
        # Vendors send a call as `function_call_arguments.done`, `output_item.done` or
        # both; the name is only sure to be in the latter.
        call_id, name = payload.get("call_id"), payload.get("name")
        arguments = payload.get("arguments")
        if not (isinstance(call_id, str) and isinstance(name, str) and name):
            return []
        if call_id in self._seen_calls:
            return []
        self._seen_calls.add(call_id)
        self._calls.append(
            ToolCall(call_id, name, arguments if isinstance(arguments, str) else "{}")
        )
        return []


def _subtitle(role: Role, payload: dict[str, Any], key: str, *, final: bool) -> list[RealtimeEvent]:
    text, item = payload.get(key), payload.get("item_id")
    if not isinstance(text, str) or not isinstance(item, str):
        return []
    return [Subtitle(role, item, text, final)]


def _usage(response: dict[str, Any]) -> Usage | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    # OpenAI says `input_token_details`, Qwen `input_tokens_details`.
    inputs = usage.get("input_token_details") or usage.get("input_tokens_details") or {}
    outputs = usage.get("output_token_details") or usage.get("output_tokens_details") or {}
    return Usage(
        input_tokens=_int(usage.get("input_tokens")),
        output_tokens=_int(usage.get("output_tokens")),
        input_audio_tokens=_int(inputs.get("audio_tokens") if isinstance(inputs, dict) else 0),
        output_audio_tokens=_int(outputs.get("audio_tokens") if isinstance(outputs, dict) else 0),
    )


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def session_settings(
    target: RealtimeTarget, instructions: str, tools: list[dict[str, Any]]
) -> dict[str, Any]:
    """The `session.update` event, in the target's spelling. `tools` are function tools
    as `{name, description, parameters}`."""
    function_tools = [{"type": "function", **tool} for tool in tools]
    if target.dialect == "ga":
        audio_in: dict[str, Any] = {
            "format": {"type": "audio/pcm", "rate": target.input_rate},
            "turn_detection": {**_VAD, "create_response": True, "interrupt_response": True},
        }
        if target.transcription:
            audio_in["transcription"] = {"model": target.transcription}
        audio_out: dict[str, Any] = {"format": {"type": "audio/pcm", "rate": target.output_rate}}
        if target.voice:
            audio_out["voice"] = target.voice
        session: dict[str, Any] = {
            "type": "realtime",
            "instructions": instructions,
            "output_modalities": ["audio"],
            "audio": {"input": audio_in, "output": audio_out},
        }
    else:
        session = {
            "modalities": ["text", "audio"],
            "instructions": instructions,
            "input_audio_format": target.formats[0],
            "output_audio_format": target.formats[1],
            "turn_detection": dict(_VAD),
        }
        if target.voice:
            session["voice"] = target.voice
        if target.transcription:
            session["input_audio_transcription"] = {"model": target.transcription}
    if function_tools:
        session["tools"] = function_tools
        session["tool_choice"] = "auto"
    return {"type": "session.update", "session": session}


async def open_session(
    target: RealtimeTarget,
    *,
    instructions: str,
    tools: list[dict[str, Any]] | None = None,
) -> RealtimeSession:
    """Connect, send the session settings and wait until the vendor accepts them.
    Raises `RealtimeConnectError`; the caller then tries the route's next target."""
    model = target.model
    if target.dialect == "gemini":
        raise RealtimeConnectError(
            f"{model.connection}:{model.model}: Gemini Live not supported yet"
        )
    parts = urlsplit(target.url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "wss" else 80)
    timeout = float(model.params.get("timeout") or SESSION_TIMEOUT)
    headers = {}
    if model.api_key is not None:
        headers["Authorization"] = f"Bearer {model.api_key.get_secret_value()}"
    ws: ClientConnection | None = None
    try:
        with anyio.fail_after(timeout):
            sock = await guarded_socket(
                host, port, allow_private=get_settings().provider_allow_private_networks
            )
        ws = await connect(
            target.url,
            sock=sock,
            additional_headers=headers,
            # Never through an environment proxy: it would bypass the address check.
            proxy=None,
            # Base64 audio barely compresses; deflate would cost memory per call.
            compression=None,
            open_timeout=timeout,
            max_size=MAX_MESSAGE_BYTES,
            user_agent_header=None,
        )
        await ws.send(json.dumps(session_settings(target, instructions, tools or [])))
        with anyio.fail_after(min(timeout, SESSION_TIMEOUT)):
            await _until_accepted(ws)
    except Exception as exc:
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        raise RealtimeConnectError(redact_key(f"{model.connection}:{model.model}: {exc}")) from exc
    return RealtimeSession(target, ws)


async def _until_accepted(ws: ClientConnection) -> None:
    async for message in ws:
        if not isinstance(message, str):
            continue
        try:
            payload = json.loads(message)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "session.updated":
            return
        if payload.get("type") == "error":
            error = payload.get("error")
            detail = error.get("message") if isinstance(error, dict) else None
            raise RuntimeError(f"session refused: {str(detail or 'error')[:300]}")
    raise RuntimeError("the vendor closed the connection")
