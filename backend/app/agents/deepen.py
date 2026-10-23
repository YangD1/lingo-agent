"""The tutor's follow-up segments (ADR 0064): when one is written, and writing it within
the tenant's limits.

The node itself is in chat_graph (it shares the tutor's prompt and history helpers);
everything here is plain functions over messages and one streaming loop.
"""

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    BaseMessageChunk,
    HumanMessage,
    message_chunk_to_message,
)
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from app.chat.deepen import DeepenSettings

logger = logging.getLogger(__name__)

CONTINUE_DEEPER = "continue_deeper"
DEEP_TASK = "chat_deep"
# additional_kwargs of a follow-up's AIMessage: which one it is this turn, and how it
# ended (ADR 0064 §7).
SEGMENT_KEY = "segment"
OUTCOME_KEY = "segment_outcome"
# What the tutor's continue_deeper call gets back; the follow-up comes after the reply.
ACK = "A follow-up will be written after your reply. Don't announce it."
# ADR 0064 §5: with follow-ups in 2 of the last 3 turns, only the rules start one.
RECENT_TURNS = 3
RECENT_LIMIT = 2
REASON_LENGTH = 120

type Trigger = Literal["rule", "model"]
# done: finished; timeout / length: stopped at the tenant's limit, what it wrote kept;
# failed: the model failed, what it wrote (if anything) kept; no_start: nothing came
# before the first-chunk limit.
type Outcome = Literal["done", "timeout", "length", "failed", "no_start"]


class ContinueDeeper(BaseModel):
    """Have a deeper follow-up written after your reply, by a model that takes longer
    to think: for a question your short answer can't do justice to. It explains what you
    left out and puts right anything you got wrong. Call it after your text, in the same
    reply; no card is shown."""

    model_config = ConfigDict(title=CONTINUE_DEEPER, extra="forbid")

    reason: str = Field(
        max_length=200, description="A few words on what the follow-up should cover."
    )


# Asking why, or how two things differ (Q124c).
_ASKS_WHY = re.compile(
    r"为什么|为啥|区别|差别|有什么不同|有何不同|不一样|\bwhy\b|\bdifferen(?:ce|t)\b|\bvs\.?\s|\bversus\b",
    re.IGNORECASE,
)
# A question mark, an English question word first, a Chinese one anywhere, or a
# sentence-final 吗 / 呢.
_QUESTION = re.compile(
    r"[?\uff1f]|^(?:how|what|why|when|which|is|are|can|could|should|do|does)\b"
    r"|怎么|怎样|如何|什么|哪|是不是|能不能|该不该|[吗呢]\W*$",
    re.IGNORECASE,
)
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
LONG_WORDS = 15
LONG_CJK = 30


def rule_fires(text: str) -> bool:
    """The learner asks why or how things differ, or asks a long question."""
    if _ASKS_WHY.search(text):
        return True
    long = len(_WORD.findall(text)) >= LONG_WORDS or len(_CJK.findall(text)) >= LONG_CJK
    return long and bool(_QUESTION.search(text.strip()))


def _turns(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
    """Messages split at each learner message, which starts its turn."""
    turns: list[list[BaseMessage]] = [[]]
    for message in messages:
        if isinstance(message, HumanMessage):
            turns.append([])
        turns[-1].append(message)
    return turns


def is_segment(message: BaseMessage) -> bool:
    return isinstance(message, AIMessage) and bool(message.additional_kwargs.get(SEGMENT_KEY))


def _calls_deeper(message: BaseMessage) -> bool:
    return isinstance(message, AIMessage) and any(
        call["name"] == CONTINUE_DEEPER for call in message.tool_calls
    )


@dataclass(frozen=True)
class TurnState:
    """Where the current turn stands on follow-ups."""

    learner_text: str | None  # None: an opening, never followed up
    segments: int
    # The tutor's continue_deeper call this turn, if it made one: its reason.
    asked: str | None
    # The latest follow-up asked for one more.
    more: bool
    # Follow-ups in 2 of the last 3 turns: only the rules start one.
    model_allowed: bool


def turn_state(messages: Sequence[BaseMessage]) -> TurnState:
    turns = _turns(messages)
    current = turns[-1]
    first = current[0] if current else None
    learner_text = first.text if isinstance(first, HumanMessage) else None
    segments = [m for m in current if is_segment(m)]
    asked = next(
        (
            str(call["args"].get("reason", ""))[:REASON_LENGTH]
            for m in current
            if isinstance(m, AIMessage) and not is_segment(m)
            for call in m.tool_calls
            if call["name"] == CONTINUE_DEEPER
        ),
        None,
    )
    earlier = [t for t in turns[:-1] if t and isinstance(t[0], HumanMessage)][-RECENT_TURNS:]
    deepened = sum(any(is_segment(m) for m in t) for t in earlier)
    return TurnState(
        learner_text=learner_text,
        segments=len(segments),
        asked=asked,
        more=bool(segments) and _calls_deeper(segments[-1]),
        model_allowed=deepened < RECENT_LIMIT,
    )


def trigger(state: TurnState, settings: DeepenSettings | None) -> Trigger | None:
    """Why the next follow-up is written, or None for no follow-up."""
    if settings is None or not settings.enabled or state.learner_text is None:
        return None
    if state.segments >= settings.max_segments:
        return None
    if state.segments:  # one more, asked for by the follow-up before it
        return "model" if state.more else None
    if rule_fires(state.learner_text):
        return "rule"
    return "model" if state.asked is not None and state.model_allowed else None


def offer(state: TurnState, settings: DeepenSettings | None) -> Literal["tool", "coming"] | None:
    """What the tutor is told: `tool` it may call continue_deeper; `coming` a follow-up
    will come anyway (a rule fired, or it asked earlier this turn); None nothing."""
    if settings is None or not settings.enabled or state.learner_text is None:
        return None
    if rule_fires(state.learner_text) or state.asked is not None:
        return "coming"
    return "tool" if state.model_allowed else None


def rough_tokens(text: str) -> int:
    """About how many tokens `text` is: a CJK character is about one, other text about
    four characters to one. For the length limit, which counts the visible text only
    (a thinking model's max_tokens would count its thinking too)."""
    cjk = len(_CJK.findall(text))
    return cjk + (len(text) - cjk + 3) // 4


def _has_output(part: BaseMessage) -> bool:
    """Text, thinking or a tool call: a chunk that shows the model has started (a
    vendor's empty first chunk doesn't)."""
    if part.text:
        return True
    if isinstance(part, AIMessage) and (part.tool_calls or getattr(part, "tool_call_chunks", None)):
        return True
    if part.additional_kwargs.get("reasoning_content"):
        return True
    content = part.content
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") in ("reasoning", "thinking") for b in content
    )


@dataclass(frozen=True)
class Segment:
    # None: nothing worth keeping was written.
    message: AIMessage | None
    outcome: Outcome


async def write_segment(
    llm: Runnable[LanguageModelInput, BaseMessage],
    messages: list[BaseMessage],
    config: RunnableConfig,
    settings: DeepenSettings,
    index: int,
    *,
    more: bool = False,
) -> Segment:
    """Stream one follow-up within the tenant's limits (ADR 0064 §5-6). A timeout,
    the length limit or a failure ends it; whatever text it wrote is kept. Its
    continue_deeper call is kept only when it may ask for `more` (some vendors return
    calls to tools they weren't offered)."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    deadline = start + settings.total_seconds
    first_by = min(deadline, start + settings.first_chunk_seconds)
    reply: BaseMessage | None = None
    started = False
    outcome: Outcome = "done"
    stream = aiter(llm.astream(messages, config))
    try:
        while True:
            try:
                async with asyncio.timeout_at(deadline if started else first_by):
                    part = await anext(stream)
            except StopAsyncIteration:
                break
            if reply is None:
                reply = part
            elif isinstance(reply, BaseMessageChunk) and isinstance(part, BaseMessageChunk):
                reply = reply + part
            else:
                raise TypeError(f"cannot merge {type(part).__name__} into a streamed reply")
            started = started or _has_output(part)
            if rough_tokens(reply.text) >= settings.max_tokens:
                outcome = "length"
                break
    except TimeoutError:
        outcome = "timeout" if started else "no_start"
    except Exception:
        logger.exception("follow-up %d failed", index)
        outcome = "failed"
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:
                logger.debug("closing the follow-up stream failed", exc_info=True)
    return Segment(_kept(reply, index, outcome, more=more), outcome)


def _kept(
    reply: BaseMessage | None, index: int, outcome: Outcome, *, more: bool
) -> AIMessage | None:
    """The follow-up as stored: its text and continue_deeper call only. Thinking stays
    out of the checkpoint (some vendors refuse it sent back)."""
    if reply is None:
        return None
    text = reply.text.strip()
    calls: list[Any] = []
    if more and outcome == "done" and isinstance(reply, AIMessage):
        calls = [c for c in _complete(reply).tool_calls if c["name"] == CONTINUE_DEEPER]
    if not text and not calls:
        return None
    return AIMessage(
        text,
        id=reply.id,
        tool_calls=calls,
        additional_kwargs={SEGMENT_KEY: index, OUTCOME_KEY: outcome},
    )


def _complete(reply: AIMessage) -> AIMessage:
    message = message_chunk_to_message(reply) if isinstance(reply, BaseMessageChunk) else reply
    assert isinstance(message, AIMessage)
    return message
