"""Tutor graph: START -> load_context -> tutor <-> tools -> END (ADR 0015 §1).

Per-run dependencies travel in LangGraph's runtime context, not in `configurable`:
`configurable` values can be copied into checkpoint metadata, and the provider
context carries decrypted API keys that must never be persisted (ADR 0004).

    await graph.astream(
        {"messages": [HumanMessage(text)]},
        config={
            "configurable": {"thread_id": str(conversation.id)},
            "metadata": {"user_id": str(user.id)},  # for llm_usage (ADR 0005)
        },
        context=ChatContext(providers=ctx),
        stream_mode=["messages", "custom"],  # custom: {"activity": ...} (ADR 0013)
    )
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    BaseMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.channels import UntrackedValue
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_config
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.activity.service import (
    STEPS,
    ActivitySink,
    ActivityStatus,
    CardShown,
    ContextRead,
    Step,
    timed,
)
from app.attachments.context import AttachmentSource, render_turn, turn_content
from app.cards.tools import TOOL_SCHEMAS, ToolOutcome, TutorTools
from app.chat.planning import PlanningBrief, PlanningSource, render_planning
from app.chat.practice import PracticeSource, render_practice
from app.memory.context import (
    LearnerContext,
    LearnerSource,
    facts_shown,
    render_learner_context,
)
from app.memory.language import DEFAULT_CHAT_LANGUAGE, ChatLanguage
from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_llm, get_llm_with_tools

logger = logging.getLogger(__name__)

LOAD_CONTEXT_NODE = "load_context"
TUTOR_NODE = "tutor"
TOOLS_NODE = "tools"

# Tool round trips per turn; the tutor's last call then has no tools and must answer.
MAX_TOOL_ROUNDS = 2
# Calls run per round; more get an error result.
MAX_CALLS_PER_ROUND = 3
TOOL_TIMEOUT_SECONDS = 15
# The tutor's calls after tool results: recorded apart from "chat", which the dashboard
# counts as the learner's turns (ADR 0015 §7).
TOOLS_USAGE_TASK = "chat_tools"
# Vendors answer a request with tools they can't take with one of these.
_REFUSED_STATUSES = frozenset({400, 404, 422})


@dataclass(frozen=True)
class ChatContext:
    providers: TenantProviderContext
    # Attachments of this conversation (ADR 0008 §4); None when a caller has none.
    attachments: AttachmentSource | None = None
    # The learner's profile and memories (ADR 0009 §4); None when a caller has none.
    learner: LearnerSource | None = None
    # Where this turn's steps are recorded for the learner (ADR 0013 §3).
    activity: ActivitySink | None = None
    # The grammar point of a practice conversation (P1 plan §7.5.3); None for free chat.
    practice: PracticeSource | None = None
    # The tutor's tools (ADR 0015); None where tools aren't bound (practice conversations).
    tools: TutorTools | None = None
    # A study-planning conversation's brief (ADR 0015 §6); None elsewhere.
    planning: PlanningSource | None = None


class ChatState(MessagesState):
    # What the tutor is told about the learner this turn. Untracked: never written to
    # the checkpoint, so memories the learner deletes leave no copy behind.
    learner_context: Annotated[str, UntrackedValue(str)]
    # Practice or planning guidance for this turn, untracked likewise so it is current.
    practice: Annotated[str, UntrackedValue(str)]
    # The conversation's cards and their status, untracked so it is current each turn.
    cards: Annotated[str, UntrackedValue(str)]
    # The language the tutor mainly talks in this turn (ADR 0017 §1), untracked so a
    # switch applies from the next reply.
    language: Annotated[ChatLanguage, UntrackedValue(str)]


# Callers send and get plain messages; learner_context is internal to a run.
type ChatGraph = CompiledStateGraph[ChatState, ChatContext, MessagesState, MessagesState]


async def load_context(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    cards = await _cards(runtime.context.tools)
    learner = runtime.context.learner
    practice = runtime.context.practice
    planning = runtime.context.planning
    if learner is None and practice is None and planning is None:
        return {
            "learner_context": "",
            "practice": "",
            "cards": cards,
            "language": DEFAULT_CHAT_LANGUAGE,
        }
    latest = next((m.text for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    context = focus = None
    brief: PlanningBrief | None = None
    failed = False
    with timed() as watch:
        # Memory and practice guidance make replies better; their failure must not stop them.
        if learner is not None:
            try:
                context = await learner.load(latest)
            except Exception:
                logger.exception("loading the learner context failed")
                failed = True
        if practice is not None:
            try:
                focus = await practice.load()
            except Exception:
                logger.exception("loading the practice focus failed")
                failed = True
        if planning is not None:
            try:
                brief = await planning.load()
            except Exception:
                logger.exception("loading the planning brief failed")
                failed = True
    if failed and context is None and focus is None and brief is None:
        await report(runtime, Step(LOAD_CONTEXT_NODE, "failed", duration_ms=watch.ms))
        return {
            "learner_context": "",
            "practice": "",
            "cards": cards,
            "language": DEFAULT_CHAT_LANGUAGE,
        }
    context = context or LearnerContext()
    read = ContextRead(
        facts=list(context.fact_ids[: facts_shown(context.facts)]),
        episodes=list(context.episode_ids),
        profile_items=len(context.profile),
        practice_kc=focus.kc.id if focus else None,
        planning=brief is not None,
    )
    await report(runtime, Step(LOAD_CONTEXT_NODE, summary=read, duration_ms=watch.ms))
    return {
        "learner_context": render_learner_context(context),
        "practice": render_practice(focus) if focus else render_planning(brief) if brief else "",
        "cards": cards,
        "language": context.chat_language,
    }


async def _cards(tools: TutorTools | None) -> str:
    if tools is None:
        return ""
    try:
        return await tools.context()
    except Exception:  # the tutor can reply without knowing its earlier cards
        logger.exception("loading the conversation's cards failed")
        return ""


async def report(runtime: Runtime[ChatContext], step: Step) -> None:
    """Record a step and stream it to the learner. Never fails the turn."""
    sink = runtime.context.activity
    if sink is None:
        return
    try:
        await sink.record(step)
    except Exception:
        logger.exception("recording the %s activity failed", step.name)
    runtime.stream_writer({"activity": step.payload(sink.turn_id)})


async def tutor(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    # The system prompt is prepended per call rather than stored in the thread, so
    # prompt edits apply to existing conversations too.
    history, has_images = await _with_attachments(state["messages"], runtime.context.attachments)
    # A turn that brings images is answered by a model configured to see them.
    task = "vision" if has_images else "chat"
    has_tools = runtime.context.tools is not None
    rounds = tool_rounds(state["messages"])
    # No tools with images (vision models may not take them), nor past the round limit.
    bind = has_tools and not has_images and rounds < MAX_TOOL_ROUNDS
    # A config passed to the model replaces the run's metadata instead of merging, so
    # start from the run's own (it carries user_id for llm_usage).
    config = get_config()
    if rounds:  # a call after tool results is not a new learner turn
        config = {
            **config,
            "metadata": {**config.get("metadata", {}), "usage_task": TOOLS_USAGE_TASK},
        }
    try:
        reply = await _call(runtime, task, state, history, has_tools, bind, config)
    except Exception as exc:
        if not (bind and getattr(exc, "status_code", None) in _REFUSED_STATUSES):
            raise
        # Some OpenAI-compatible servers reject tools; answer this turn without them.
        logger.warning("tool calling refused (%s); replying without tools", type(exc).__name__)
        await report(runtime, Step("tools", "skipped"))
        reply = await _call(runtime, task, state, history, has_tools, False, config)
    return {"messages": [reply]}


async def _call(
    runtime: Runtime[ChatContext],
    task: str,
    state: ChatState,
    history: list[BaseMessage],
    has_tools: bool,
    bind: bool,
    config: RunnableConfig,
) -> BaseMessage:
    llm: Runnable[Any, BaseMessage] = (
        get_llm_with_tools(runtime.context.providers, task, TOOL_SCHEMAS)
        if bind
        else get_llm(runtime.context.providers, task)
    )
    tools_section = ""
    if has_tools:
        cards = state.get("cards", "") or "(none)"
        tools_section = load_prompt("tutor_tools" if bind else "tutor_no_tools").replace(
            "{cards}", cards
        )
    prompt = system_prompt(
        state.get("learner_context", ""),
        state.get("practice", ""),
        tools_section,
        language=state.get("language") or DEFAULT_CHAT_LANGUAGE,
    )
    messages = [SystemMessage(prompt), *history]
    if not any(isinstance(m, HumanMessage) for m in history):
        # An opening: the learner hasn't written yet. Some providers need a user turn,
        # so the cue goes in as one, for this call only.
        cue = "plan_opening" if runtime.context.planning is not None else "practice_opening"
        messages.append(HumanMessage(load_prompt(cue)))
    # astream, not ainvoke: if the learner disconnects, the run is cancelled, and only
    # astream reports that to callbacks (ainvoke's internal gather is cancelled before
    # on_llm_error runs), so llm_usage would miss a call the provider still bills for.
    reply: BaseMessage | None = None
    async for part in llm.astream(messages, config):
        # Streaming models yield chunks to merge; others yield one complete message.
        if reply is None:
            reply = part
        elif isinstance(reply, BaseMessageChunk) and isinstance(part, BaseMessageChunk):
            reply = reply + part
        else:
            raise TypeError(f"cannot merge {type(part).__name__} into a streamed reply")
    if reply is None:
        raise ValueError("chat model returned no output")
    return message_chunk_to_message(reply) if isinstance(reply, BaseMessageChunk) else reply


def tool_rounds(messages: Sequence[BaseMessage]) -> int:
    """Tool round trips so far in the current turn (since the last learner message)."""
    rounds = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and message.tool_calls:
            rounds += 1
    return rounds


def after_tutor(state: ChatState) -> str:
    last = state["messages"][-1]
    return TOOLS_NODE if isinstance(last, AIMessage) and last.tool_calls else END


async def run_tools(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    """Run the last reply's tool calls concurrently; a failure becomes that call's
    result, never the turn's (ADR 0013 §1)."""
    last = state["messages"][-1]
    assert isinstance(last, AIMessage)
    results = await asyncio.gather(
        *(_run_call(runtime, call, i) for i, call in enumerate(last.tool_calls))
    )
    return {"messages": list(results)}


async def _run_call(runtime: Runtime[ChatContext], call: ToolCall, index: int) -> ToolMessage:
    tools = runtime.context.tools
    name = call["name"]
    # Card writes are keyed by the call id; a vendor that leaves it out gets a fresh one.
    call_id = call.get("id") or f"call-{uuid.uuid4().hex}"
    with timed() as watch:
        if tools is None:
            outcome = ToolOutcome("Error: tools are not available here.", ok=False)
        elif index >= MAX_CALLS_PER_ROUND:
            outcome = ToolOutcome(
                f"Error: at most {MAX_CALLS_PER_ROUND} tool calls at a time; not run.", ok=False
            )
        else:
            try:
                async with asyncio.timeout(TOOL_TIMEOUT_SECONDS):
                    outcome = await tools.run(name, call["args"], call_id)
            except Exception:
                logger.exception("tool %s failed", name)
                outcome = ToolOutcome(
                    "Error: the tool failed. Tell the learner to try again.", ok=False
                )
    if outcome.card is not None:
        runtime.stream_writer({"card": outcome.card})
    if name in STEPS and STEPS[name].kind == "tool":  # a made-up name has no activity row
        card = outcome.card or {}
        summary = CardShown(card_id=card.get("id"), card_kind=card.get("kind"))
        status: ActivityStatus = "ok" if outcome.ok else "failed"
        await report(runtime, Step(name, status, summary, watch.ms, call_id=call_id))
    return ToolMessage(
        outcome.content,
        tool_call_id=call_id,
        name=name,
        status="success" if outcome.ok else "error",
    )


def system_prompt(
    learner_context: str,
    practice: str = "",
    tools: str = "",
    *,
    language: ChatLanguage = DEFAULT_CHAT_LANGUAGE,
) -> str:
    """The tutor's instructions and which language to talk in, then what it knows about
    the learner, then (in a practice or planning conversation) what this conversation is
    for, then what its tools can do."""
    sections = [load_prompt("tutor_system"), load_prompt(f"language_{language}")]
    if learner_context:
        # replace, not format: memories may contain braces.
        sections.append(
            load_prompt("learner_context").replace("{learner_context}", learner_context)
        )
    if practice:
        sections.append(practice)
    if tools:
        sections.append(tools)
    return "\n\n".join(sections)


async def _with_attachments(
    messages: Sequence[BaseMessage], source: AttachmentSource | None
) -> tuple[list[BaseMessage], bool]:
    """Expand learner messages with their attachments, for this call only.

    Nothing here is written back to the state: the checkpoint keeps plain text, and
    original images go only with the turn they were sent in.
    """
    human_ids = [m.id for m in messages if isinstance(m, HumanMessage) and m.id]
    if source is None or not human_ids:
        return list(messages), False
    attached = await source.by_message(human_ids)
    if not attached:
        return list(messages), False
    current = human_ids[-1]
    has_images = False
    expanded: list[BaseMessage] = []
    for message in messages:
        items = attached.get(message.id or "") if isinstance(message, HumanMessage) else None
        if not items:
            expanded.append(message)
            continue
        rendered = render_turn(message.text, items)
        images = []
        if message.id == current:
            images = await source.images([a.id for a in items if a.kind == "image"])
            has_images = bool(images)
        expanded.append(HumanMessage(turn_content(rendered, images), id=message.id))
    return expanded, has_images


def build_chat_graph(checkpointer: BaseCheckpointSaver[Any]) -> ChatGraph:
    builder = StateGraph(
        ChatState,
        context_schema=ChatContext,
        input_schema=MessagesState,
        output_schema=MessagesState,
    )
    builder.add_node(LOAD_CONTEXT_NODE, load_context)
    builder.add_node(TUTOR_NODE, tutor)
    builder.add_node(TOOLS_NODE, run_tools)
    builder.add_edge(START, LOAD_CONTEXT_NODE)
    builder.add_edge(LOAD_CONTEXT_NODE, TUTOR_NODE)
    builder.add_conditional_edges(TUTOR_NODE, after_tutor, [TOOLS_NODE, END])
    builder.add_edge(TOOLS_NODE, TUTOR_NODE)
    return builder.compile(checkpointer=checkpointer)
