"""The `gemini_live` adapter (ADR 0030 §2): a `RealtimeSession` over Gemini Live's
`BidiGenerateContent` WebSocket (checked 2026-10-11, `ai.google.dev/api/live`).

The first message is `setup` (model, instructions, tools, server-side voice activity
detection, subtitles on both sides, context compression, resumption); nothing else may
be sent before `setupComplete`. The key can only go in the address's query string, so
everything that may quote the address goes through `redact_key`.

Gemini's events don't map one to one onto the neutral ones:

- There are no turn ids: they are made up here, one per learner turn and per reply.
- A learner turn is committed (`LearnerTurn`) when the model starts answering it; its
  subtitle keeps taking text until the model's turn is complete, since the learner's
  transcript often comes late. Subtitles have no final marker: the text gathered so
  far is the final subtitle at `turnComplete`.
- `interrupted` is the learner talking over the tutor (`SpeechStarted`). The server
  stops the reply on its own, so `interrupt` sends nothing.
- A `toolCall` ends the reply so far (`ResponseDone`, then `ToolCalls`); the model
  goes on by itself once it has the results, so there is no separate "respond".
- `respond` can't give per-reply instructions: it sends them as a user turn of text.

A connection lasts about ten minutes: `goAway` warns of the end, and the session is
resumed on a new connection with the latest resumption handle, at a point the server
says is resumable. What the relay sends meanwhile is held and sent after; only a
failed resumption ends the call.

Vendor messages are untrusted: anything unknown is dropped, missing fields skip the
event. Gemini sends its JSON in binary frames as well as text ones.
"""

import base64
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import anyio
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from app.providers.realtime import RealtimeTarget, redact_key
from app.providers.realtime_session import (
    SESSION_TIMEOUT,
    AudioOut,
    LearnerTurn,
    RealtimeConnectError,
    RealtimeEvent,
    ResponseDone,
    Role,
    SpeechStarted,
    Subtitle,
    ToolCall,
    ToolCalls,
    Usage,
    VendorError,
    connect_ws,
)

logger = logging.getLogger(__name__)

# Server-side voice activity detection (Q60d), as for the OpenAI protocol.
_VAD: dict[str, Any] = {"disabled": False, "prefixPaddingMs": 300, "silenceDurationMs": 500}
# The opening reply has nothing to answer: the tutor speaks first (Q58e) on this cue,
# the instructions saying what to say.
START_CUE = "(The learner has joined the call.)"
# What the relay may send while a connection is being replaced: about 30 s of audio.
MAX_HELD_BYTES = 1024 * 1024


class _Refused(Exception):
    pass


def setup_message(
    target: RealtimeTarget, instructions: str, tools: list[dict[str, Any]], handle: str | None
) -> dict[str, Any]:
    """The `setup` message; `handle` resumes an earlier session."""
    name = target.model.model
    generation: dict[str, Any] = {"responseModalities": ["AUDIO"]}
    if target.voice:
        generation["speechConfig"] = {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": target.voice}}
        }
    setup: dict[str, Any] = {
        "model": name if name.startswith("models/") else f"models/{name}",
        "generationConfig": generation,
        "systemInstruction": {"parts": [{"text": instructions}]},
        "realtimeInputConfig": {"automaticActivityDetection": dict(_VAD)},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        # Without it an audio session stops at 15 minutes.
        "contextWindowCompression": {"slidingWindow": {}},
        "sessionResumption": {"handle": handle} if handle else {},
    }
    if tools:
        setup["tools"] = [{"functionDeclarations": [_declaration(tool) for tool in tools]}]
    return {"setup": setup}


def _declaration(tool: dict[str, Any]) -> dict[str, Any]:
    declaration = {"name": tool["name"], "description": tool.get("description", "")}
    parameters = tool.get("parameters") or {}
    # Gemini refuses an object schema with no properties: a tool without arguments
    # declares none.
    if parameters.get("properties"):
        declaration["parameters"] = _schema(parameters)
    return declaration


def _schema(schema: Any) -> Any:
    """JSON Schema to Gemini's OpenAPI subset: type names are its enum values."""
    if isinstance(schema, list):
        return [_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    converted = {key: _schema(value) for key, value in schema.items()}
    if isinstance(schema.get("type"), str):
        converted["type"] = schema["type"].upper()
    if isinstance(schema.get("properties"), dict):
        converted["properties"] = {k: _schema(v) for k, v in schema["properties"].items()}
    return converted


@dataclass
class GeminiLiveSession:
    target: RealtimeTarget
    _ws: ClientConnection
    _url: str  # with the key: never logged
    _setup: dict[str, Any]
    _timeout: float
    # Resumption: the latest handle, and whether the session may be resumed now.
    _handle: str | None = None
    _resumable: bool = False
    _going_away: bool = False
    _resume_now: bool = False
    _resuming: bool = False
    _held: list[str] = field(default_factory=list)
    _held_bytes: int = 0
    # The turn in progress; ids are made up (`g1`, `g2`, ...).
    _ids: int = 0
    _learner: str | None = None
    _learner_text: str = ""
    _learner_committed: bool = False
    _tutor: str | None = None
    _tutor_text: str = ""
    _interrupted: bool = False
    _usage: Usage | None = None
    _call_names: dict[str, str] = field(default_factory=dict)
    _cancelled: set[str] = field(default_factory=set)

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
        audio = {
            "data": base64.b64encode(pcm).decode(),
            "mimeType": f"audio/pcm;rate={self.target.input_rate}",
        }
        await self._send({"realtimeInput": {"audio": audio}})

    async def interrupt(self, played_ms: int | None = None) -> None:
        """Nothing to do: the server stops the reply when the learner talks over it."""

    async def respond(self, instructions: str | None = None) -> None:
        text = instructions or START_CUE
        await self._send(
            {
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": text}]}],
                    "turnComplete": True,
                }
            }
        )

    async def send_tool_results(
        self, results: list[tuple[str, str]], *, respond: bool = True
    ) -> None:
        """The model goes on by itself once it has the results, `respond` or not; a call
        the server has cancelled gets none."""
        responses = [
            {
                "id": call_id,
                "name": self._call_names.get(call_id, ""),
                "response": _response(output),
            }
            for call_id, output in results
            if call_id not in self._cancelled
        ]
        if responses:
            await self._send({"toolResponse": {"functionResponses": responses}})

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            try:
                async for message in self._ws:
                    payload = _parse(message)
                    if payload is not None:
                        for event in self._translate(payload):
                            yield event
                    if self._resume_now:
                        break
            except ConnectionClosed:
                pass
            if self._going_away and await self._resume():
                continue
            if self._resume_now:  # resuming failed early: the old connection goes on
                self._resume_now = self._going_away = False
                continue
            for event in self._turn_complete("incomplete", only_started=True):
                yield event
            code, reason = self._ws.close_code, self._ws.close_reason
            if code not in (None, 1000):
                yield VendorError(str(code), redact_key(reason or "")[:500])
            return

    async def _send(self, message: dict[str, Any]) -> None:
        text = json.dumps(message)
        if self._resuming:
            self._hold(text)
            return
        try:
            await self._ws.send(text)
        except ConnectionClosed:
            # The server is about to hang up for resumption: it goes on the next one.
            if not self._going_away:
                raise
            self._hold(text)

    def _hold(self, text: str) -> None:
        if self._held_bytes + len(text) > MAX_HELD_BYTES:
            return
        self._held.append(text)
        self._held_bytes += len(text)

    async def _resume(self) -> bool:
        """Carry on on a new connection with the latest handle (the old one is told to
        go away). False: the session can't be resumed."""
        if self._handle is None:
            return False
        self._resuming = True
        try:
            setup = {
                "setup": {**self._setup["setup"], "sessionResumption": {"handle": self._handle}}
            }
            ws = await _handshake(self._url, setup, self._timeout)
        except Exception as exc:
            logger.warning("gemini live resumption failed: %s", redact_key(str(exc)))
            self._resuming = False
            self._held, self._held_bytes = [], 0
            return False
        old, self._ws = self._ws, ws
        with contextlib.suppress(Exception):
            await old.close()
        self._going_away = self._resume_now = self._resumable = False
        # Sent in order; what the relay sends meanwhile joins the end of the queue.
        while self._held:
            await ws.send(self._held.pop(0))
        self._held_bytes = 0
        self._resuming = False
        return True

    def _translate(self, payload: dict[str, Any]) -> list[RealtimeEvent]:
        events: list[RealtimeEvent] = []
        if isinstance(usage := payload.get("usageMetadata"), dict):
            self._usage = _usage(usage)
        if isinstance(content := payload.get("serverContent"), dict):
            events += self._content(content)
        if isinstance(call := payload.get("toolCall"), dict):
            events += self._tool_calls(call)
        if isinstance(cancelled := payload.get("toolCallCancellation"), dict):
            ids = cancelled.get("ids")
            if isinstance(ids, list):
                self._cancelled.update(i for i in ids if isinstance(i, str))
        if isinstance(update := payload.get("sessionResumptionUpdate"), dict):
            handle = update.get("newHandle")
            if isinstance(handle, str) and handle:
                self._handle = handle
            self._resumable = update.get("resumable") is True
            if self._going_away and self._resumable and self._handle:
                self._resume_now = True
        if "goAway" in payload:
            self._going_away = True
            self._resume_now = self._resumable and self._handle is not None
        return events

    def _content(self, content: dict[str, Any]) -> list[RealtimeEvent]:
        events: list[RealtimeEvent] = []
        if isinstance(heard := content.get("inputTranscription"), dict):
            text = heard.get("text")
            if isinstance(text, str) and text:
                if self._learner is None:
                    self._learner, self._learner_text = self._new_id(), ""
                    self._learner_committed = False
                self._learner_text += text
                events.append(Subtitle("learner", self._learner, text, False))
        if content.get("interrupted") is True:
            # Late text for the turn just answered would now be taken as new speech.
            events += self._learner_done(committed_only=True)
            self._interrupted = True
            events.append(SpeechStarted())
        if isinstance(turn := content.get("modelTurn"), dict) and not self._interrupted:
            parts = turn.get("parts")
            for part in parts if isinstance(parts, list) else []:
                audio = _audio(part)
                if audio:
                    events += self._tutor_started()
                    events.append(AudioOut(audio))
        if isinstance(said := content.get("outputTranscription"), dict) and not self._interrupted:
            text = said.get("text")
            if isinstance(text, str) and text:
                events += self._tutor_started()
                assert self._tutor is not None
                self._tutor_text += text
                events.append(Subtitle("tutor", self._tutor, text, False))
        if content.get("turnComplete") is True:
            events += self._turn_complete("cancelled" if self._interrupted else "completed")
        return events

    def _tool_calls(self, call: dict[str, Any]) -> list[RealtimeEvent]:
        found: list[ToolCall] = []
        calls = call.get("functionCalls")
        for item in calls if isinstance(calls, list) else []:
            if not isinstance(item, dict):
                continue
            call_id, name, args = item.get("id"), item.get("name"), item.get("args")
            if not (isinstance(call_id, str) and call_id and isinstance(name, str) and name):
                continue
            if call_id in self._call_names:
                continue
            self._call_names[call_id] = name
            found.append(
                ToolCall(call_id, name, json.dumps(args if isinstance(args, dict) else {}))
            )
        if not found:
            return []
        events = self._tutor_started()
        # The reply so far is done; the model goes on once it has the results.
        events += self._tutor_done("completed")
        events.append(ToolCalls(tuple(found)))
        return events

    def _new_id(self) -> str:
        self._ids += 1
        return f"g{self._ids}"

    def _tutor_started(self) -> list[RealtimeEvent]:
        """The model is answering: the learner's turn before it is committed."""
        events: list[RealtimeEvent] = []
        if self._learner is not None and not self._learner_committed:
            self._learner_committed = True
            events.append(LearnerTurn(self._learner))
        if self._tutor is None:
            self._tutor, self._tutor_text = self._new_id(), ""
        return events

    def _learner_done(self, *, committed_only: bool) -> list[RealtimeEvent]:
        if self._learner is None or (committed_only and not self._learner_committed):
            return []
        line = _final("learner", self._learner, self._learner_text)
        self._learner, self._learner_text, self._learner_committed = None, "", False
        return line

    def _tutor_done(self, status: str) -> list[RealtimeEvent]:
        events: list[RealtimeEvent] = []
        if self._tutor is not None and not self._interrupted:
            events += _final("tutor", self._tutor, self._tutor_text)
        events.append(ResponseDone(status, self._usage))
        self._tutor, self._tutor_text, self._usage = None, "", None
        return events

    def _turn_complete(self, status: str, *, only_started: bool = False) -> list[RealtimeEvent]:
        if only_started and self._tutor is None:
            return []
        events = self._learner_done(committed_only=True)
        events += self._tutor_done(status)
        self._interrupted = False
        return events


def _final(role: Role, item_id: str, text: str) -> list[RealtimeEvent]:
    return [Subtitle(role, item_id, text, True)]


def _parse(message: str | bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(message)
    except ValueError:  # includes undecodable bytes
        return None
    return payload if isinstance(payload, dict) else None


def _audio(part: Any) -> bytes | None:
    if not isinstance(part, dict) or not isinstance(inline := part.get("inlineData"), dict):
        return None
    data, mime = inline.get("data"), inline.get("mimeType")
    if not isinstance(data, str) or not (isinstance(mime, str) and mime.startswith("audio/")):
        return None
    try:
        return base64.b64decode(data, validate=True) or None
    except ValueError:
        return None


def _response(output: str) -> dict[str, Any]:
    """A function response is an object: JSON results as they are, others wrapped."""
    try:
        value = json.loads(output)
    except ValueError:
        value = output
    return value if isinstance(value, dict) else {"output": value}


def _usage(usage: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=_int(usage.get("promptTokenCount")),
        output_tokens=_int(usage.get("responseTokenCount")),
        input_audio_tokens=_audio_tokens(usage.get("promptTokensDetails")),
        output_audio_tokens=_audio_tokens(usage.get("responseTokensDetails")),
    )


def _audio_tokens(details: Any) -> int:
    if not isinstance(details, list):
        return 0
    return sum(
        _int(item.get("tokenCount"))
        for item in details
        if isinstance(item, dict) and item.get("modality") == "AUDIO"
    )


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


async def _handshake(url: str, setup: dict[str, Any], wait: float) -> ClientConnection:
    ws = await connect_ws(url, {}, wait)
    try:
        await ws.send(json.dumps(setup))
        with anyio.fail_after(min(wait, SESSION_TIMEOUT)):
            async for message in ws:
                payload = _parse(message)
                if payload is not None and "setupComplete" in payload:
                    return ws
        # Gemini refuses a session by closing the connection with the reason.
        raise _Refused(f"session refused: {ws.close_code} {(ws.close_reason or '')[:300]}")
    except BaseException:
        with contextlib.suppress(Exception):
            await ws.close()
        raise


async def open_gemini_session(
    target: RealtimeTarget,
    *,
    instructions: str,
    tools: list[dict[str, Any]] | None = None,
) -> GeminiLiveSession:
    """See `realtime_session.open_session`."""
    model = target.model
    timeout = float(model.params.get("timeout") or SESSION_TIMEOUT)
    setup = setup_message(target, instructions, tools or [], None)
    try:
        if model.api_key is None:
            raise _Refused("no API key")
        separator = "&" if "?" in target.url else "?"
        url = f"{target.url}{separator}key={quote(model.api_key.get_secret_value(), safe='')}"
        ws = await _handshake(url, setup, timeout)
    except Exception as exc:
        raise RealtimeConnectError(redact_key(f"{model.connection}:{model.model}: {exc}")) from exc
    return GeminiLiveSession(target, ws, url, setup, timeout)
