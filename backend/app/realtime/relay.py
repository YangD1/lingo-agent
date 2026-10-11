"""The relay between the browser and the vendor for one realtime call (ADR 0030 §1).

Browser -> backend: binary frames are the learner's PCM16 audio at the vendor's input
rate (Q60a, Q60b); text frames are JSON, of which only `interrupt` and `end` are read
(ADR 0030 §1 white list), anything else is dropped. Backend -> browser: binary frames
are the tutor's audio; text frames are JSON events:

    ready           {session_id, conversation_id, input_rate, output_rate, limit_seconds}
    subtitle        {role: learner|tutor, item_id, text, final}
    speech_started  the learner started talking: stop playing the tutor
    response_done   the tutor finished a reply
    tool            a tool the tutor used: {turn_id, name, kind, call_id, status,
                    duration_ms, summary}, as the chat stream's activity (ADR 0013)
    end_suggested   the tutor suggests hanging up; the learner decides (Q61c)
    time_warning    {remaining_seconds}: the call ends soon (ADR 0030 §5)
    wrapping_up     time is up: the tutor says goodbye, the learner's audio is ignored
    error           {code}: the vendor reported an error; the call may go on
    ended           {reason}: last message before the backend closes the socket

Both sides' final subtitles are saved to the call's conversation a reply at a time
(`transcript.py`, Q61e). The audio is never decoded (ADR 0030 §1); the learner's is
metered so a client can't send it faster than real time, which the vendor would bill as
audio tokens.
"""

import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

import anyio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activity import service as activity
from app.prompts import load_prompt
from app.providers.realtime_session import (
    AudioOut,
    LearnerTurn,
    RealtimeSession,
    ResponseDone,
    SpeechStarted,
    Subtitle,
    ToolCall,
    ToolCalls,
    VendorError,
)
from app.realtime import calls
from app.realtime.limits import WARNING_SECONDS
from app.realtime.tools import CallTools, Outcome, failed
from app.realtime.transcript import Line, Transcript
from app.usage.recorder import UsageRecord, submit_usage

logger = logging.getLogger(__name__)

TASK = "realtime"  # llm_usage label (ADR 0030 §1)
# The largest audio frame accepted from the browser: about 1.3 s at 24 kHz.
MAX_FRAME_BYTES = 64 * 1024
# How far ahead of real time the learner's audio may run (network bursts).
AUDIO_BURST_SECONDS = 2.0
# How often the call's duration is written down (a restart loses at most this much).
PROGRESS_SECONDS = 15.0
# After the time limit, how long the tutor has to say goodbye before the call is cut.
WRAP_UP_SECONDS = 10.0
# Tool calls per reply and per call, and how long one may take (Q61d).
MAX_TOOLS_PER_REPLY = 3
MAX_TOOLS_PER_CALL = 20
TOOL_TIMEOUT_SECONDS = 3.0

type EndReason = Literal[
    "hangup", "vendor_closed", "time_limit", "server_stopping", "browser_closed", "error"
]


class BrowserSocket(Protocol):
    async def receive(self) -> bytes | str | None:
        """The next frame; None once the browser has gone."""
        ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def send_json(self, data: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class CallInfo:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID
    conversation_id: uuid.UUID
    limit_seconds: float
    # Connected to a later model in the route, the first ones having failed.
    is_fallback: bool = False


class RealtimeCall:
    def __init__(
        self,
        browser: BrowserSocket,
        vendor: RealtimeSession,
        info: CallInfo,
        maker: async_sessionmaker[AsyncSession],
        save: Callable[[list[Line]], Awaitable[None]],
        tools: CallTools,
        *,
        clock: Callable[[], float] = time.monotonic,
        tick_seconds: float = 1.0,
    ) -> None:
        self._browser = browser
        self._vendor = vendor
        self._info = info
        self._maker = maker
        self._save = save
        self._tools = tools
        self._tool_calls = 0
        self._transcript = Transcript()
        self._clock = clock
        self._tick = tick_seconds
        self._started = clock()
        self._reason: EndReason | None = None
        self._scope: anyio.CancelScope | None = None
        # Learner audio sent since the last reply, for that reply's usage row.
        self._audio_bytes = 0
        self._audio_total = 0
        self._reply_started: float | None = None
        # Time is up: the goodbye is asked for once the reply in progress is done.
        self._wrapping = False
        self._goodbye_asked = False

    @property
    def user_id(self) -> uuid.UUID:
        return self._info.user_id

    @property
    def elapsed(self) -> float:
        return self._clock() - self._started

    def stop(self, reason: str) -> None:
        """End the call from outside (shutdown)."""
        self._end(reason)  # type: ignore[arg-type]

    async def run(self) -> EndReason:
        target = self._vendor.target
        try:
            await self._browser.send_json(
                {
                    "type": "ready",
                    "session_id": str(self._info.session_id),
                    "conversation_id": str(self._info.conversation_id),
                    "input_rate": target.input_rate,
                    "output_rate": target.output_rate,
                    "limit_seconds": int(self._info.limit_seconds),
                }
            )
            # The tutor speaks first (Q58e); what to say is in the instructions.
            await self._vendor.respond()
            async with anyio.create_task_group() as tg:
                self._scope = tg.cancel_scope
                if self._reason is not None:  # stopped before it got going
                    tg.cancel_scope.cancel()
                tg.start_soon(self._from_browser)
                tg.start_soon(self._from_vendor)
                tg.start_soon(self._clock_loop)
        except Exception:
            logger.exception("realtime call %s failed", self._info.session_id)
            self._reason = self._reason or "error"
        finally:
            reason: EndReason = self._reason or "error"
            await self._vendor.close()
            await self._save_lines(self._transcript.take_all())
            with anyio.CancelScope(shield=True):
                try:
                    await calls.finish(self._maker, self._info.session_id, self.elapsed)
                except Exception:
                    logger.exception("could not close realtime call %s", self._info.session_id)
                with contextlib.suppress(Exception):
                    await self._browser.send_json({"type": "ended", "reason": reason})
                with contextlib.suppress(Exception):
                    await self._browser.close()
        return reason

    def _end(self, reason: EndReason) -> None:
        if self._reason is None:
            self._reason = reason
        if self._scope is not None:
            self._scope.cancel()

    async def _from_browser(self) -> None:
        while True:
            frame = await self._browser.receive()
            if frame is None:
                self._end("browser_closed")
                return
            if isinstance(frame, bytes):
                await self._learner_audio(frame)
                continue
            try:
                message = json.loads(frame)
            except ValueError:
                continue
            kind = message.get("type") if isinstance(message, dict) else None
            if kind == "end":
                self._end("hangup")
                return
            if kind == "interrupt":
                played = message.get("played_ms")
                await self._vendor.interrupt(
                    played if isinstance(played, int) and not isinstance(played, bool) else None
                )

    async def _learner_audio(self, frame: bytes) -> None:
        if self._wrapping:  # the learner talking would cut the goodbye short
            return
        rate = self._vendor.target.input_rate * 2  # PCM16 mono: bytes per second
        allowed = (self.elapsed + AUDIO_BURST_SECONDS) * rate
        # Odd lengths would split a sample; too-large or too-fast audio is dropped.
        if not frame or len(frame) % 2 or len(frame) > MAX_FRAME_BYTES:
            return
        if self._audio_total + len(frame) > allowed:
            return
        self._audio_total += len(frame)
        self._audio_bytes += len(frame)
        await self._vendor.send_audio(frame)

    async def _from_vendor(self) -> None:
        async for event in self._vendor.events():
            match event:
                case AudioOut(data=data):
                    self._reply_started = self._reply_started or self._clock()
                    await self._browser.send_bytes(data)
                case LearnerTurn(item_id=item_id):
                    self._transcript.learner_turn(item_id)
                case Subtitle():
                    self._transcript.subtitle(event)
                    if event.role == "tutor":
                        self._reply_started = self._reply_started or self._clock()
                    await self._browser.send_json(
                        {
                            "type": "subtitle",
                            "role": event.role,
                            "item_id": event.item_id,
                            "text": event.text,
                            "final": event.final,
                        }
                    )
                case SpeechStarted():
                    self._transcript.speech_started()
                    await self._browser.send_json({"type": "speech_started"})
                case ResponseDone():
                    self._record(event)
                    await self._browser.send_json({"type": "response_done"})
                    self._transcript.response_done(event.status)
                    await self._save_lines(self._transcript.take_settled())
                    if self._goodbye_asked:
                        self._end("time_limit")
                    elif self._wrapping:
                        await self._say_goodbye()
                case ToolCalls(calls=tool_calls):
                    await self._run_tools(tool_calls)
                case VendorError(code=code):
                    logger.info("realtime vendor error %s", code)
                    # The vendor's message can echo request details; the code is enough.
                    await self._browser.send_json({"type": "error", "code": code})
        self._end("vendor_closed")

    async def _clock_loop(self) -> None:
        limit = self._info.limit_seconds
        saved = 0.0
        # A call no longer than the warning period gets no warning.
        warned = limit <= WARNING_SECONDS
        while True:
            await anyio.sleep(self._tick)
            elapsed = self.elapsed
            if elapsed >= limit + WRAP_UP_SECONDS:
                self._end("time_limit")
                return
            if elapsed >= limit and not self._wrapping:
                self._wrapping = True
                await self._browser.send_json({"type": "wrapping_up"})
                # Asking mid-reply would be refused; that reply's end asks instead.
                if self._reply_started is None:
                    await self._say_goodbye()
            elif not warned and elapsed >= limit - WARNING_SECONDS:
                warned = True
                remaining = max(0, round(limit - elapsed))
                await self._browser.send_json(
                    {"type": "time_warning", "remaining_seconds": remaining}
                )
            if elapsed - saved >= PROGRESS_SECONDS:
                saved = elapsed
                await calls.save_progress(self._maker, self._info.session_id, elapsed)

    async def _run_tools(self, tool_calls: tuple[ToolCall, ...]) -> None:
        """Run one reply's calls together and give the results back (ADR 0013): a
        failure, a timeout or a call over the limits is a result, never the end of the
        call. Once time is up they are only answered: the goodbye is on its way."""
        outcomes: list[Outcome | None] = [None] * len(tool_calls)

        async def run(index: int, call: ToolCall) -> None:
            started = self._clock()
            try:
                with anyio.fail_after(TOOL_TIMEOUT_SECONDS):
                    outcome = await self._tools.run(call.name, call.call_id, call.arguments)
            except TimeoutError:
                outcome = failed(call.name, call.call_id, "timed out")
            except Exception:
                logger.exception("realtime tool %s failed", call.name)
                outcome = failed(call.name, call.call_id, "failed")
            if outcome.step is not None:
                duration = int((self._clock() - started) * 1000)
                outcome = replace(outcome, step=replace(outcome.step, duration_ms=duration))
            outcomes[index] = outcome

        async with anyio.create_task_group() as tg:
            for index, call in enumerate(tool_calls):
                if self._wrapping:
                    outcomes[index] = failed(call.name, call.call_id, "the call is ending")
                elif index >= MAX_TOOLS_PER_REPLY or self._tool_calls >= MAX_TOOLS_PER_CALL:
                    outcomes[index] = failed(call.name, call.call_id, "too many tool calls")
                else:
                    self._tool_calls += 1
                    tg.start_soon(run, index, call)

        turn_id = self._transcript.turn_id()
        results: list[tuple[str, str]] = []
        for call, outcome in zip(tool_calls, outcomes, strict=True):
            assert outcome is not None
            results.append((call.call_id, outcome.output))
            if outcome.step is not None:
                await self._show(turn_id, outcome)
        await self._vendor.send_tool_results(results, respond=not self._wrapping)

    async def _show(self, turn_id: str, outcome: Outcome) -> None:
        """What the tutor did, kept with the call's conversation and shown live."""
        step = outcome.step
        assert step is not None
        try:
            async with self._maker() as session:
                await activity.record(
                    session,
                    user_id=self._info.user_id,
                    conversation_id=self._info.conversation_id,
                    turn_id=turn_id,
                    name=step.name,
                    status=step.status,
                    summary=step.summary,
                    duration_ms=step.duration_ms,
                    call_id=step.call_id,
                )
                await session.commit()
        except Exception:
            logger.exception("could not record realtime tool %s", step.name)
        await self._browser.send_json({"type": "tool", **step.payload(turn_id)})
        if outcome.suggest_end:
            await self._browser.send_json({"type": "end_suggested"})

    async def _save_lines(self, lines: list[Line]) -> None:
        """A failed save loses those lines, never the call. Shielded: a hang-up during
        the save would otherwise cut the query off and leave the connection unusable."""
        try:
            with anyio.CancelScope(shield=True):
                await self._save(lines)
        except Exception:
            logger.exception("could not save realtime call %s transcript", self._info.session_id)

    async def _say_goodbye(self) -> None:
        self._goodbye_asked = True
        await self._vendor.respond(load_prompt("realtime_wrap_up"))

    def _record(self, done: ResponseDone) -> None:
        model = self._vendor.target.model
        rate = self._vendor.target.input_rate * 2
        started = self._reply_started or self._clock()
        usage = done.usage
        submit_usage(
            UsageRecord(
                tenant_id=self._info.tenant_id,
                user_id=self._info.user_id,
                conversation_id=self._info.conversation_id,
                task=TASK,
                connection_name=model.connection,
                model=model.model,
                # Audio tokens are part of these totals (ADR 0030 §1).
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                latency_ms=int((self._clock() - started) * 1000),
                status="error" if done.status == "failed" else "ok",
                is_fallback=self._info.is_fallback,
                error_code=None,
                audio_seconds=round(self._audio_bytes / rate, 2),
            )
        )
        self._audio_bytes = 0
        self._reply_started = None
