"""LangChain callback that turns each chat-model call into a `UsageRecord`.

One recorder is attached to each cached model, so it knows the tenant, task,
connection, model and chain position up front. Who the call was for comes from the
run's metadata at invoke time, because cached models are shared by a whole tenant:

    await graph.ainvoke(state, config={"metadata": {"user_id": str(user.id)}})

LangGraph copies `configurable["thread_id"]` into metadata by itself, so a graph
keyed by conversation id gets `conversation_id` for free. Missing ids are fine
(background jobs have neither); the row is still written with NULLs.

A retry sets `attempt` (2 for the first retry, ...; ADR 0056 §5). A call cancelled
because the vendor stalled is cancelled with `STALLED` as the message, so it is
recorded as `stalled`, not `cancelled`.

A run may also set `usage_task` to record the call under another task than the one
that routed it, e.g. a practice opening served by the chat model but not counted as a
learner's chat turn. Work nobody is waiting for that counts against the tenant's daily
background budget (ADR 0025 §5) sets `background: True`.

Only metadata is recorded - never prompts, completions or exception messages. Which
prompt templates a call used, and their versions, is metadata (ADR 0033 §2).
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, GenerationChunk, LLMResult

from app.prompts import prompt_versions

logger = logging.getLogger(__name__)

# Runs that never report back (should not happen: astream catches BaseException) must
# not grow a shared, long-lived recorder without bound.
_MAX_PENDING_RUNS = 10_000

# The cancel message of a call stopped because the vendor sent nothing for too long.
STALLED = "lingo:stalled"


@dataclass(frozen=True)
class UsageLabels:
    """What a recorder knows when its model is built."""

    tenant_id: uuid.UUID
    task: str
    connection: str
    model: str
    # Only reached when every earlier model in the task's chain failed.
    is_fallback: bool = False
    # The main account paying, when a member uses its connection (ADR 0031 §6).
    billed_tenant_id: uuid.UUID | None = None
    section: str = "llm"


@dataclass(frozen=True)
class UsageRecord:
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    task: str
    connection_name: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: str  # "ok" | "error" | "cancelled" | "stalled"
    is_fallback: bool
    error_code: str | None
    audio_seconds: float | None = None
    background: bool = False
    # Text-to-speech bills by characters (ADR 0028 §1).
    characters: int | None = None
    # ADR 0031 §6: the main account paying (None: the tenant), and the call's section.
    billed_tenant_id: uuid.UUID | None = None
    section: str | None = None
    # `{prompt name: version}` the call used (ADR 0033 §2); None: none recognised.
    prompts: dict[str, str] | None = None
    # Input tokens read from the vendor's prompt cache (ADR 0053 §1); None: not reported.
    cached_input_tokens: int | None = None
    # Streamed calls: when the first chunk arrived (ADR 0056 §5).
    first_chunk_ms: int | None = None
    attempt: int = 1


UsageSink = Callable[[UsageRecord], None]


@dataclass
class _PendingRun:
    started: float
    user_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    task: str | None
    background: bool
    prompts: dict[str, str] | None
    attempt: int
    first_chunk: float | None = None


def _as_uuid(value: Any) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _attempt(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 1


def _token_counts(response: LLMResult) -> tuple[int, int, int | None]:
    """Input, output and cached input tokens of the call."""
    for generations in response.generations:
        for generation in generations:
            if isinstance(generation, ChatGeneration) and isinstance(generation.message, AIMessage):
                usage = generation.message.usage_metadata
                if usage:
                    return usage["input_tokens"], usage["output_tokens"], _cached(usage)
    return 0, 0, None


def _cached(usage: UsageMetadata) -> int | None:
    # langchain-openai prefixes the key with the service tier ("priority_cache_read").
    details: Mapping[str, Any] = usage.get("input_token_details") or {}
    reads = [v for k, v in details.items() if k.endswith("cache_read") and v is not None]
    return sum(reads) if reads else None


class UsageRecorder(BaseCallbackHandler):
    """Synchronous and inline on purpose.

    langchain-core's async dispatch calls inline sync handlers directly, *before* it
    `asyncio.gather`s the rest. A client disconnect cancels the SSE producer through
    an anyio cancel scope, which is level-triggered: that gather is cancelled before
    any async handler runs, so an async recorder silently loses cancelled calls - the
    ones the provider still bills for. The work here is CPU-only (no I/O), so running
    inline costs nothing.
    """

    run_inline = True

    def __init__(self, labels: UsageLabels, sink: UsageSink) -> None:
        self.labels = labels
        self._sink = sink
        self._pending: dict[uuid.UUID, _PendingRun] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        meta: Mapping[str, Any] = metadata or {}
        if len(self._pending) >= _MAX_PENDING_RUNS:
            logger.warning("usage recorder dropping %d unfinished runs", len(self._pending))
            self._pending.clear()
        self._pending[run_id] = _PendingRun(
            started=time.monotonic(),
            user_id=_as_uuid(meta.get("user_id")),
            conversation_id=_as_uuid(meta.get("conversation_id") or meta.get("thread_id")),
            task=str(meta["usage_task"])[:64] if meta.get("usage_task") else None,
            background=meta.get("background") is True,
            prompts=prompt_versions("\n".join(m.text for batch in messages for m in batch)),
            attempt=_attempt(meta.get("attempt")),
        )

    def on_llm_new_token(
        self,
        token: str | list[str | dict[str, Any]],
        *,
        chunk: GenerationChunk | ChatGenerationChunk | None = None,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        run = self._pending.get(run_id)
        if run is not None and run.first_chunk is None:
            run.first_chunk = time.monotonic()

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        input_tokens, output_tokens, cached = _token_counts(response)
        self._finish(run_id, "ok", None, input_tokens, output_tokens, cached)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        # The class name only: messages can echo request content.
        self._finish(run_id, _status(error), type(error).__name__[:64], 0, 0)

    def _finish(
        self,
        run_id: uuid.UUID,
        status: str,
        error_code: str | None,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int | None = None,
    ) -> None:
        run = self._pending.pop(run_id, None)
        if run is None:  # not a chat-model run we saw start
            return
        labels = self.labels
        first_chunk = run.first_chunk
        record = UsageRecord(
            tenant_id=labels.tenant_id,
            user_id=run.user_id,
            conversation_id=run.conversation_id,
            task=run.task or labels.task,
            connection_name=labels.connection,
            model=labels.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.monotonic() - run.started) * 1000),
            status=status,
            is_fallback=labels.is_fallback,
            error_code=error_code,
            background=run.background,
            billed_tenant_id=labels.billed_tenant_id,
            section=labels.section,
            prompts=run.prompts,
            cached_input_tokens=cached_input_tokens,
            first_chunk_ms=None if first_chunk is None else int((first_chunk - run.started) * 1000),
            attempt=run.attempt,
        )
        try:
            self._sink(record)
        except Exception:  # usage accounting must never break a model call
            logger.exception("failed to submit usage record")


def _status(error: BaseException) -> str:
    if isinstance(error, asyncio.CancelledError):
        return "stalled" if error.args == (STALLED,) else "cancelled"
    return "error"


# --- process-wide sink --------------------------------------------------------------------

_sink: UsageSink | None = None


def set_usage_sink(sink: UsageSink | None) -> None:
    """Install where records go (the app's UsageWriter); None drops them."""
    global _sink
    _sink = sink


def submit_usage(record: UsageRecord) -> None:
    if _sink is not None:
        _sink(record)


def make_recorder(labels: UsageLabels) -> UsageRecorder:
    """Recorder that forwards to whatever sink is installed when the call finishes."""
    return UsageRecorder(labels, submit_usage)
