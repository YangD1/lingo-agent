"""Tutor graph: START -> load_context -> tutor <-> tools -> deepen -> END (ADR 0015 §1,
ADR 0064).

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
from typing import Annotated, Any, Literal

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
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel

from app.activity.service import (
    STEPS,
    ActivitySink,
    ActivityStatus,
    CardShown,
    ContextRead,
    FollowUpWritten,
    Handoff,
    ReadingContextRead,
    SkillLoaded,
    Step,
    WorkspaceContextRead,
    timed,
)
from app.adaptive.rules import get_rules
from app.agents.deepen import (
    ACK,
    CONTINUE_DEEPER,
    DEEP_TASK,
    ContinueDeeper,
    offer,
    trigger,
    turn_state,
    write_segment,
)
from app.agents.messages import StampedMessagesState
from app.agents.routing import Route, classify, worth_classifying
from app.attachments.context import AttachmentSource, render_turn, turn_content
from app.cards.tools import TOOL_SCHEMAS, ToolOutcome, TutorTools
from app.chat.deepen import MAX_SEGMENTS, DeepenSettings
from app.chat.lesson import LessonBrief, LessonSource, lesson_opening_cue, render_lesson
from app.chat.planning import PlanningBrief, PlanningSource, render_planning
from app.chat.practice import PracticeSource, render_practice
from app.chat.reading import ReadingSource, render_reading
from app.chat.speaking import SpeakingFocus, SpeakingSource, focus_for, opening_cue, render_speaking
from app.chat.writing import WritingSource, failed
from app.memory.context import (
    LearnerContext,
    LearnerSource,
    facts_shown,
    render_learner_context,
)
from app.memory.language import DEFAULT_CHAT_LANGUAGE, ChatLanguage
from app.prompts import load_prompt
from app.providers.config import TenantProviderContext, TutorPick
from app.providers.llm import get_llm, get_llm_with_tools
from app.skills.tool import (
    LOAD_SKILL,
    LoadSkill,
    SkillKey,
    read_earlier,
    read_skill,
    skill_key,
    skills_section,
)
from app.tutor.prompt import tutor_name
from app.workspace.context import WorkspaceSource, render_workspace

logger = logging.getLogger(__name__)

LOAD_CONTEXT_NODE = "load_context"
SUPERVISOR_NODE = "supervisor"
# Each coach is a subgraph under its route's name (ADR 0023 §2); its replying node has
# the same name, which is what streamed tokens are tagged with.
TUTOR_NODE = Route.TUTOR.value
GRAMMAR_COACH_NODE = Route.GRAMMAR_COACH.value
WRITING_COACH_NODE = Route.WRITING_COACH.value
READING_COACH_NODE = Route.READING_COACH.value
SPEAKING_COACH_NODE = Route.SPEAKING_COACH.value
COACH_NODES = frozenset(
    {TUTOR_NODE, GRAMMAR_COACH_NODE, WRITING_COACH_NODE, READING_COACH_NODE, SPEAKING_COACH_NODE}
)
TOOLS_NODE = "tools"
# After the tutor, in the parent graph: the tutor's reply is checkpointed before its
# follow-ups start, so stopping one never loses the reply (ADR 0064 §6).
DEEPEN_NODE = "deepen"

# Tool round trips per turn; the tutor's last call then has no tools and must answer.
MAX_TOOL_ROUNDS = 2
# Rounds that only read skills are counted apart (ADR 0055 §6): reading one must not cost
# the tutor its chance to show a card. Past these, they count as ordinary rounds.
MAX_SKILL_ROUNDS = 2
# Backstop per (sub)graph run (ADR 0013): LangGraph 1.x defaults to 10,007 steps. The tutor
# takes 2 * (MAX_TOOL_ROUNDS + MAX_SKILL_ROUNDS) + 1; the outer graph a few.
RECURSION_LIMIT = 2 * (MAX_TOOL_ROUNDS + MAX_SKILL_ROUNDS) + 6 + MAX_SEGMENTS
# Card tool calls run per round; more get an error result. load_skill calls aren't counted.
MAX_CALLS_PER_ROUND = 3
# What the tutor is offered: the card tools and load_skill.
TUTOR_TOOL_SCHEMAS: tuple[type[BaseModel], ...] = (*TOOL_SCHEMAS, LoadSkill)
TOOL_TIMEOUT_SECONDS = 15
# Cards whose results the tutor need not pass on: a reply that wrote its text and showed
# only these ends with the tools (ADR 0057).
SHORTCUT_TOOLS = frozenset({"suggest_link", "suggest_practice"})
# The tutor's calls after tool results: recorded apart from "chat", which the dashboard
# counts as the learner's turns (ADR 0015 §7).
TOOLS_USAGE_TASK = "chat_tools"
# reading_coach's replies, likewise apart from "chat" (Q43i).
READING_USAGE_TASK = "reading_coach"
# speaking_coach's replies, likewise (ADR 0029 §7).
SPEAKING_USAGE_TASK = "speaking"
# What a coach is told when it speaks first: only planning and daily conversations (the
# tutor's; a daily one from the desk pet, ADR 0041) and practice conversations
# (grammar_coach's) open by themselves.
PLAN_CUE = "plan_opening"
DAILY_CUE = "daily_opening"
PRACTICE_CUE = "practice_opening"
WORKSPACE_CONTEXT = "workspace_context"
# An ordinary conversation's section: question, "you decide" or chat (ADR 0054 §3).
FREE_CHAT = "free_chat"
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
    # A lesson conversation's material (ADR 0044 §5); None elsewhere.
    lesson: LessonSource | None = None
    # The coach that answers this turn (ADR 0023 §3).
    route: Route = Route.TUTOR
    # Free chat: the supervisor may classify the turn and hand it to another coach.
    classify: bool = False
    # Reviews writing_coach's text (task 38.5); None where a caller has none.
    writing: WritingSource | None = None
    # reading_coach's article (Q43h); None where a caller has none.
    reading: ReadingSource | None = None
    # speaking_coach's scenario and level (ADR 0029 §2); None where a caller has none.
    speaking: SpeakingSource | None = None
    # The document open in the workspace beside the chat (ADR 0043 §6); None when none.
    workspace: WorkspaceSource | None = None
    # The tenant's limits on follow-ups (ADR 0064 §5); None: this turn gets none (not
    # free chat, an opening, images, or the tenant turned them off).
    deepen: DeepenSettings | None = None


class ChatState(StampedMessagesState):
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
    # The document open in the workspace, untracked: it changes between turns.
    workspace: Annotated[str, UntrackedValue(str)]


# Callers send and get plain messages; learner_context is internal to a run.
type ChatGraph = CompiledStateGraph[
    ChatState, ChatContext, StampedMessagesState, StampedMessagesState
]


async def load_context(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    return {**await _load_context(state, runtime), "workspace": await _workspace(runtime)}


async def _workspace(runtime: Runtime[ChatContext]) -> str:
    source = runtime.context.workspace
    if source is None:
        return ""
    with timed() as watch:
        try:
            focus = await source.load()
        except Exception:  # the coach can reply without the document
            logger.exception("loading the workspace document failed")
            focus = None
    if focus is None:
        await report(runtime, Step(WORKSPACE_CONTEXT, "failed", duration_ms=watch.ms))
        return ""
    read = WorkspaceContextRead(doc_id=focus.doc_id, version=focus.version, words=focus.words)
    await report(runtime, Step(WORKSPACE_CONTEXT, summary=read, duration_ms=watch.ms))
    return render_workspace(focus)


async def _load_context(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    cards = await _cards(runtime.context.tools)
    learner = runtime.context.learner
    practice = runtime.context.practice
    planning = runtime.context.planning
    lesson = runtime.context.lesson
    if learner is None and practice is None and planning is None and lesson is None:
        return {
            "learner_context": "",
            "practice": "",
            "cards": cards,
            "language": DEFAULT_CHAT_LANGUAGE,
        }
    latest = next((m.text for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    context = focus = None
    brief: PlanningBrief | None = None
    taught: LessonBrief | None = None
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
        if lesson is not None:
            try:
                taught = await lesson.load()
            except Exception:
                logger.exception("loading the lesson failed")
                failed = True
    if failed and context is None and focus is None and brief is None and taught is None:
        await report(runtime, Step(LOAD_CONTEXT_NODE, "failed", duration_ms=watch.ms))
        return {
            "learner_context": "",
            "practice": "",
            "cards": cards,
            "language": DEFAULT_CHAT_LANGUAGE,
        }
    context = context or LearnerContext()
    # Set only for a learner's message in free chat (Turn.free_chat).
    free_chat = runtime.context.classify
    read = ContextRead(
        facts=list(context.fact_ids[: facts_shown(context.facts)]),
        episodes=list(context.episode_ids),
        profile_items=len(context.profile),
        practice_kc=focus.kc.id if focus else taught.lesson.kc.id if taught else None,
        planning=brief is not None,
        progress=bool(context.progress),
    )
    await report(runtime, Step(LOAD_CONTEXT_NODE, summary=read, duration_ms=watch.ms))
    return {
        "learner_context": render_learner_context(context),
        "practice": (
            render_practice(focus)
            if focus
            else render_planning(brief)
            if brief
            else render_lesson(taught)
            if taught
            else load_prompt(FREE_CHAT)
            if free_chat
            else ""
        ),
        "cards": cards,
        "language": context.chat_language,
    }


async def _lesson_brief(lesson: LessonSource) -> LessonBrief | None:
    """Loaded once per turn already (load_context); a failure opens it as a new lesson."""
    try:
        return await lesson.load()
    except Exception:
        logger.exception("loading the lesson failed")
        return None


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
    history = skills_read_earlier(history)
    # A turn that brings images is answered by a model configured to see them.
    task = "vision" if has_images else "chat"
    has_tools = runtime.context.tools is not None
    rounds = tool_rounds(state["messages"])
    # No tools with images (vision models may not take them), nor past the round limit.
    bind = has_tools and not has_images and rounds < MAX_TOOL_ROUNDS
    # A config passed to the model replaces the run's metadata instead of merging, so
    # start from the run's own (it carries user_id for llm_usage).
    config = get_config()
    if _turn_rounds(state["messages"]):  # a call after tool results is not a new learner turn
        config = {
            **config,
            "metadata": {**config.get("metadata", {}), "usage_task": TOOLS_USAGE_TASK},
        }
    planning = runtime.context.planning
    if runtime.context.lesson:
        cue = lesson_opening_cue(await _lesson_brief(runtime.context.lesson))
    else:
        cue = load_prompt(DAILY_CUE if planning and planning.purpose == "daily" else PLAN_CUE)
    # What the tutor is told about follow-ups (ADR 0064 §3); none with images, which
    # the follow-up model may not see.
    offered = None if has_images else offer(turn_state(state["messages"]), runtime.context.deepen)
    try:
        reply = await _call(
            runtime, task, state, history, has_tools, bind, config, cue, deepen=offered
        )
    except Exception as exc:
        if not (bind and getattr(exc, "status_code", None) in _REFUSED_STATUSES):
            raise
        # Some OpenAI-compatible servers reject tools; answer this turn without them.
        logger.warning("tool calling refused (%s); replying without tools", type(exc).__name__)
        await report(runtime, Step("tools", "skipped"))
        reply = await _call(
            runtime, task, state, history, has_tools, False, config, cue, deepen=offered
        )
        bind = False
    if not bind:
        reply = _offered_none(reply)
    return {"messages": [reply]}


async def deepen(state: ChatState, runtime: Runtime[ChatContext]) -> Command[str]:
    """The tutor's follow-up (ADR 0064): when a rule fires or the tutor asked for one,
    the chat_deep model writes it under the reply, within the tenant's limits. Each
    follow-up is a node run of its own, so the ones before it are kept if it's stopped.
    A failure ends the follow-ups, never the turn."""
    settings = runtime.context.deepen
    messages = state["messages"]
    turn = turn_state(messages)
    why = trigger(turn, settings)
    if why is None or settings is None:
        return Command(goto=END)
    index = turn.segments + 1
    more = index < settings.max_segments
    history, _ = await _with_attachments(messages, runtime.context.attachments)
    history = without_tool_calls(skills_read_earlier(history))
    rules = load_prompt("tutor_deepen")
    if more:
        rules = f"{rules}\n\n{load_prompt('tutor_deepen_more')}"
    prompt = system_prompt(
        state.get("learner_context", ""),
        tools=rules,
        workspace=state.get("workspace", ""),
        language=state.get("language") or DEFAULT_CHAT_LANGUAGE,
        name=pick.name if (pick := runtime.context.providers.tutor) else None,
    )
    call = [SystemMessage(prompt), *history, HumanMessage(load_prompt("tutor_deepen_cue"))]
    runtime.stream_writer({"segment": {"index": index, "state": "started"}})
    with timed() as watch:
        try:
            providers = runtime.context.providers
            llm: Runnable[Any, BaseMessage] = (
                get_llm_with_tools(providers, DEEP_TASK, [ContinueDeeper])
                if more
                else get_llm(providers, DEEP_TASK)
            )
        except Exception:  # no usable model: the reply stands alone
            logger.exception("no model for the follow-up")
            segment = None
        else:
            segment = await write_segment(llm, call, get_config(), settings, index, more=more)
    outcome = segment.outcome if segment is not None else "failed"
    runtime.stream_writer({"segment": {"index": index, "state": "ended", "outcome": outcome}})
    kept = segment.message if segment is not None else None
    status: ActivityStatus = (
        "ok" if kept is not None else "skipped" if outcome in ("done", "no_start") else "failed"
    )
    summary = FollowUpWritten(
        segment=index,
        trigger=why,
        outcome=outcome,
        reason=turn.asked if why == "model" and index == 1 else None,
    )
    await report(runtime, Step("deepen", status, summary, watch.ms, call_id=str(index)))
    if kept is None:
        return Command(goto=END)
    update: list[BaseMessage] = [kept]
    # Every tool call needs its result, or the next request on this history is refused.
    update.extend(_ack(call) for call in kept.tool_calls)
    return Command(update={"messages": update}, goto=DEEPEN_NODE if kept.tool_calls else END)


def _ack(call: ToolCall) -> ToolMessage:
    return ToolMessage(
        ACK, tool_call_id=call.get("id") or "", name=CONTINUE_DEEPER, status="success"
    )


def _offered_none(reply: BaseMessage) -> BaseMessage:
    """Drop tool calls from a reply that was offered no tools. Some providers return them
    anyway (Bailian's qwen-plus when streaming, after earlier rounds); run, they would
    loop past MAX_TOOL_ROUNDS until the learner left."""
    if not isinstance(reply, AIMessage) or not (
        reply.tool_calls or reply.invalid_tool_calls or "tool_calls" in reply.additional_kwargs
    ):
        return reply
    logger.warning("dropped %d tool calls from a reply offered no tools", len(reply.tool_calls))
    kwargs = {k: v for k, v in reply.additional_kwargs.items() if k != "tool_calls"}
    return reply.model_copy(
        update={"tool_calls": [], "invalid_tool_calls": [], "additional_kwargs": kwargs}
    )


async def grammar_coach(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    """A practice conversation's coach: it stays on the grammar point, without tools
    (ADR 0015 §2), and opens the conversation by itself."""
    history, has_images = await _with_attachments(state["messages"], runtime.context.attachments)
    task = "vision" if has_images else "chat"
    reply = await _call(
        runtime, task, state, history, False, False, get_config(), load_prompt(PRACTICE_CUE)
    )
    return {"messages": [reply]}


async def writing_coach(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    """Free chat handed over for a piece of the learner's writing: the text is always
    reviewed (Q38b), a card links to the review, and the coach comments on it briefly,
    without tools."""
    history, has_images = await _with_attachments(state["messages"], runtime.context.attachments)
    task = "vision" if has_images else "chat"
    source = runtime.context.writing
    latest = next((m.text for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    if source is None:
        outcome = failed()
    else:
        with timed() as watch:
            try:
                outcome = await source.review(latest)
            except Exception:  # the coach can still reply without the review
                logger.exception("reviewing the learner's writing failed")
                outcome = failed()
        if outcome.card is not None:
            runtime.stream_writer({"card": outcome.card})
        step = Step("writing_review", outcome.status, outcome.summary, watch.ms)
        await report(runtime, step)
        if outcome.workspace is not None:
            runtime.stream_writer({"card": outcome.workspace})
            await report(runtime, Step("workspace_opened", summary=outcome.opened))
    guided: ChatState = {**state, "practice": outcome.guidance}
    reply = await _call(
        runtime,
        task,
        guided,
        without_tool_calls(history),
        False,
        False,
        get_config(),
        load_prompt(PLAN_CUE),
    )
    return {"messages": [reply]}


async def reading_coach(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    """A conversation opened from an article (Q43h): each turn the coach is given the
    article, at the learner's level when that version is ready, and answers about it,
    without tools (Q43i). It never speaks first."""
    history, has_images = await _with_attachments(state["messages"], runtime.context.attachments)
    task = "vision" if has_images else "chat"
    source = runtime.context.reading
    focus = None
    if source is not None:
        with timed() as watch:
            try:
                focus = await source.load()
            except Exception:  # the coach can still reply, saying it can't see the article
                logger.exception("loading the article for reading_coach failed")
        if focus is None:
            step = Step("reading_context", "failed", duration_ms=watch.ms)
        else:
            read = ReadingContextRead(
                article_id=focus.article_id, level=focus.level, words=focus.words
            )
            step = Step("reading_context", summary=read, duration_ms=watch.ms)
        await report(runtime, step)
    guided: ChatState = {**state, "practice": render_reading(focus)}
    config = get_config()
    config = {
        **config,
        "metadata": {**config.get("metadata", {}), "usage_task": READING_USAGE_TASK},
    }
    reply = await _call(
        runtime,
        task,
        guided,
        without_tool_calls(history),
        False,
        False,
        config,
        load_prompt(PLAN_CUE),
    )
    return {"messages": [reply]}


async def speaking_coach(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    """A speaking conversation's partner (ADR 0029 §2): it plays the scenario's role in
    short spoken English, recasts instead of correcting, has no tools (Q58f), and speaks
    first (Q58e). It always talks in English, whatever the learner's chat language."""
    focus: SpeakingFocus | None = None
    if runtime.context.speaking is not None:
        try:
            focus = await runtime.context.speaking.load()
        except Exception:  # the coach can still talk, without the scenario
            logger.exception("loading the speaking scenario failed")
    focus = focus or focus_for(None, None, get_rules())
    guided: ChatState = {**state, "practice": render_speaking(focus), "language": "en"}
    history = without_tool_calls(state["messages"])
    config = get_config()
    if any(isinstance(m, HumanMessage) for m in history):  # an opening keeps its own task
        config = {
            **config,
            "metadata": {**config.get("metadata", {}), "usage_task": SPEAKING_USAGE_TASK},
        }
    reply = await _call(
        runtime,
        "chat",
        guided,
        history,
        False,
        False,
        config,
        opening_cue(focus),
        base="speaking_coach",
    )
    return {"messages": [reply]}


def without_tool_calls(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """History for a coach without tools: the tutor's earlier tool calls and their
    results are left out (some vendors refuse tool messages in a request without tool
    definitions); the text of those replies stays."""
    kept: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            continue
        if isinstance(message, AIMessage) and message.tool_calls:
            if message.text:
                kept.append(AIMessage(message.text, id=message.id))
            continue
        kept.append(message)
    return kept


async def _call(
    runtime: Runtime[ChatContext],
    task: str,
    state: ChatState,
    history: list[BaseMessage],
    has_tools: bool,
    bind: bool,
    config: RunnableConfig,
    opening_cue: str,
    *,
    base: str = "tutor_system",
    deepen: Literal["tool", "coming"] | None = None,
) -> BaseMessage:
    # continue_deeper only with the other tools: a call past the round limit has none.
    deeper = deepen == "tool" and bind
    schemas: tuple[type[BaseModel], ...] = (
        (*TUTOR_TOOL_SCHEMAS, ContinueDeeper) if deeper else TUTOR_TOOL_SCHEMAS
    )
    llm: Runnable[Any, BaseMessage] = (
        get_llm_with_tools(runtime.context.providers, task, schemas)
        if bind
        else get_llm(runtime.context.providers, task)
    )
    tools_section = ""
    if has_tools:
        cards = state.get("cards", "") or "(none)"
        tools_section = load_prompt("tutor_tools" if bind else "tutor_no_tools").replace(
            "{cards}", cards
        )
        if bind:
            tutor = runtime.context.providers.tutor
            tools_section = tools_section.replace(
                "{workspace_rule}", workspace_rule(tutor)
            ).replace("{quiz_rule}", quiz_rule(tutor, lesson=runtime.context.lesson is not None))
    if deeper or deepen == "coming":
        rule = load_prompt("tutor_deepen_tool" if deeper else "tutor_deepen_coming")
        tools_section = f"{tools_section}\n\n{rule}" if tools_section else rule
    prompt = system_prompt(
        state.get("learner_context", ""),
        state.get("practice", ""),
        tools_section,
        workspace=state.get("workspace", ""),
        language=state.get("language") or DEFAULT_CHAT_LANGUAGE,
        base=base,
        name=pick.name if (pick := runtime.context.providers.tutor) else None,
        skills=skills_section() if has_tools else "",
    )
    messages: list[BaseMessage] = [SystemMessage(prompt)]
    if not any(isinstance(m, HumanMessage) for m in history):
        # An opening: the learner hasn't written yet. Some providers need a user turn,
        # so the cue goes in as one, for this call only, before the opening's own tool
        # rounds: last, it read as a new request and the tutor began again each round.
        messages.append(HumanMessage(opening_cue))
    messages.extend(history)
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


def workspace_rule(tutor: TutorPick | None) -> str:
    """Whether the tutor opens the workspace by itself (ADR 0045 §1, §3)."""
    auto = tutor is None or tutor.workspace_auto_open
    return load_prompt("tutor_workspace_auto" if auto else "tutor_workspace_on_request")


def quiz_rule(tutor: TutorPick | None, *, lesson: bool) -> str:
    """Whether the tutor gives quizzes nobody asked for (ADR 0046 §3-4); a lesson is
    there to be tested, whatever the setting."""
    proactive = lesson or tutor is None or tutor.quiz_proactive
    return load_prompt("tutor_quiz_proactive" if proactive else "tutor_quiz_on_request")


def _turn_rounds(messages: Sequence[BaseMessage]) -> list[AIMessage]:
    """The replies with tool calls in the current turn (since the last learner message)."""
    rounds: list[AIMessage] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and message.tool_calls:
            rounds.append(message)
    return rounds


def _only_skills(reply: AIMessage) -> bool:
    return all(call["name"] == LOAD_SKILL for call in reply.tool_calls)


def tool_rounds(messages: Sequence[BaseMessage]) -> int:
    """Tool round trips so far in the current turn that count against MAX_TOOL_ROUNDS:
    rounds that only read skills are free up to MAX_SKILL_ROUNDS."""
    rounds = _turn_rounds(messages)
    skill_rounds = sum(_only_skills(r) for r in rounds)
    return len(rounds) - skill_rounds + max(0, skill_rounds - MAX_SKILL_ROUNDS)


def _skill_calls(messages: Sequence[BaseMessage]) -> dict[str, SkillKey]:
    """load_skill calls by tool call id, with the (skill, part) each asked for."""
    calls: dict[str, SkillKey] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call["name"] == LOAD_SKILL and call.get("id"):
                    key = skill_key(call["args"])
                    if key is not None:
                        calls[str(call["id"])] = key
    return calls


def skills_read_earlier(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Skills read in earlier turns stay out of later ones (ADR 0055 §6): their results
    become a line saying so, for this call only (the checkpoint keeps them), so each turn's
    input doesn't keep growing."""
    last_human = _last_human(messages)
    calls = _skill_calls(messages[:last_human])
    kept: list[BaseMessage] = []
    for i, message in enumerate(messages):
        if (
            i < last_human
            and isinstance(message, ToolMessage)
            and message.status == "success"
            and (key := calls.get(message.tool_call_id)) is not None
        ):
            message = message.model_copy(update={"content": read_earlier(key)})
        kept.append(message)
    return kept


def _last_human(messages: Sequence[BaseMessage]) -> int:
    """Index of the learner's latest message, -1 before they write."""
    return max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)


def after_tutor(state: ChatState) -> str:
    last = state["messages"][-1]
    return TOOLS_NODE if isinstance(last, AIMessage) and last.tool_calls else END


def after_tools(state: ChatState) -> str:
    """Done when the tutor wrote its reply and only showed shortcut cards that worked
    (ADR 0057): their results say nothing new, so another call would only add a line.
    Anything else goes back to the tutor: a failed call to put right, a result to pass
    on, or a reply with no text yet."""
    messages = state["messages"]
    i = len(messages)
    while i > 0 and isinstance(messages[i - 1], ToolMessage):
        i -= 1
    called = messages[i - 1] if i > 0 else None
    results = messages[i:]
    if not (
        isinstance(called, AIMessage)
        and called.tool_calls
        and all(isinstance(r, ToolMessage) and r.status == "success" for r in results)
    ):
        return TUTOR_NODE
    names = {call["name"] for call in called.tool_calls}
    # continue_deeper says nothing new either: the follow-up comes next (ADR 0064 §3),
    # and a reply that only asked for one has its text written there.
    if names == {CONTINUE_DEEPER} or (
        called.text.strip() and names <= SHORTCUT_TOOLS | {CONTINUE_DEEPER}
    ):
        return END
    return TUTOR_NODE


async def run_tools(state: ChatState, runtime: Runtime[ChatContext]) -> dict[str, Any]:
    """Run the last reply's tool calls concurrently; a failure becomes that call's
    result, never the turn's (ADR 0013 §1)."""
    last = state["messages"][-1]
    assert isinstance(last, AIMessage)
    # Skills this turn has read, each read once (ADR 0055 §6); a repeat in this same
    # round counts as read by the first call asking for it.
    read = _read_this_turn(state)
    runs = []
    index = 0
    for call in last.tool_calls:
        if call["name"] == LOAD_SKILL:
            runs.append(_run_skill(runtime, call, frozenset(read)))
            if (key := skill_key(call["args"])) is not None:
                read.add(key)
        elif call["name"] == CONTINUE_DEEPER:
            # Recorded by the deepen node, with the follow-up it starts (ADR 0064 §9).
            runs.append(_ack_deeper(call))
        else:
            runs.append(_run_call(runtime, call, index))
            index += 1
    results = await asyncio.gather(*runs)
    return {"messages": list(results)}


async def _ack_deeper(call: ToolCall) -> ToolMessage:
    return _ack(call)


def _read_this_turn(state: ChatState) -> set[SkillKey]:
    """What load_skill read since the learner last wrote."""
    messages = state["messages"]
    last_human = _last_human(messages)
    turn = messages[last_human + 1 :]
    calls = _skill_calls(turn)
    return {
        calls[m.tool_call_id]
        for m in turn
        if isinstance(m, ToolMessage) and m.status == "success" and m.tool_call_id in calls
    }


async def _run_skill(
    runtime: Runtime[ChatContext], call: ToolCall, already: frozenset[SkillKey]
) -> ToolMessage:
    call_id = call.get("id") or f"call-{uuid.uuid4().hex}"
    with timed() as watch:
        outcome = read_skill(call["args"], already)
    if outcome.read is not None:
        skill, part = outcome.read
        summary = SkillLoaded(skill=skill, part=part)
        await report(runtime, Step(LOAD_SKILL, "ok", summary, watch.ms, call_id=call_id))
    elif not outcome.ok:  # a repeat records nothing: nothing new was read
        await report(runtime, Step(LOAD_SKILL, "failed", duration_ms=watch.ms, call_id=call_id))
    return ToolMessage(
        outcome.content,
        tool_call_id=call_id,
        name=LOAD_SKILL,
        status="success" if outcome.ok else "error",
    )


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
    base: str = "tutor_system",
    name: str | None = None,
    workspace: str = "",
    skills: str = "",
) -> str:
    """The tutor's instructions, the name the learner gave it, which language to talk in
    and the skills it can read (the part that stays the same, ADR 0053 §1), then what it
    knows about the learner, then (in a practice or planning conversation) what this
    conversation is for, then what its tools can do."""
    sections = [load_prompt(base), *tutor_name(name), load_prompt(f"language_{language}")]
    if skills:
        sections.append(skills)
    if learner_context:
        # replace, not format: memories may contain braces.
        sections.append(
            load_prompt("learner_context").replace("{learner_context}", learner_context)
        )
    if practice:
        sections.append(practice)
    if workspace:
        sections.append(workspace)
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


async def supervisor(
    state: ChatState, runtime: Runtime[ChatContext]
) -> Command[Literal["tutor", "grammar_coach", "writing_coach", "reading_coach", "speaking_coach"]]:
    """Hand the turn to its coach. The route is decided before the run from what is
    certain about the conversation (ADR 0023 §3); only a long enough free-chat message
    is classified (Q38a), and a handoff is shown to the learner (Q37b)."""
    route = runtime.context.route
    messages = state["messages"]
    latest = messages[-1] if messages else None
    if (
        runtime.context.classify
        and route is Route.TUTOR
        and isinstance(latest, HumanMessage)
        and worth_classifying(latest.text)
    ):
        previous = next(
            (m.text for m in reversed(messages) if isinstance(m, AIMessage) and m.text), ""
        )
        with timed() as watch:
            route = await classify(runtime.context.providers, latest.text, previous, get_config())
        if route is not Route.TUTOR:
            handoff = Handoff(coach=route.value)
            await report(runtime, Step("handoff", summary=handoff, duration_ms=watch.ms))
    return Command(goto=route.value)


def _tutor_graph() -> CompiledStateGraph[ChatState, ChatContext, ChatState, ChatState]:
    builder = StateGraph(ChatState, context_schema=ChatContext)
    builder.add_node(TUTOR_NODE, tutor)
    builder.add_node(TOOLS_NODE, run_tools)
    builder.add_edge(START, TUTOR_NODE)
    builder.add_conditional_edges(TUTOR_NODE, after_tutor, [TOOLS_NODE, END])
    builder.add_conditional_edges(TOOLS_NODE, after_tools, [TUTOR_NODE, END])
    return builder.compile(checkpointer=False)


def _grammar_coach_graph() -> CompiledStateGraph[ChatState, ChatContext, ChatState, ChatState]:
    builder = StateGraph(ChatState, context_schema=ChatContext)
    builder.add_node(GRAMMAR_COACH_NODE, grammar_coach)
    builder.add_edge(START, GRAMMAR_COACH_NODE)
    builder.add_edge(GRAMMAR_COACH_NODE, END)
    return builder.compile(checkpointer=False)


def _writing_coach_graph() -> CompiledStateGraph[ChatState, ChatContext, ChatState, ChatState]:
    builder = StateGraph(ChatState, context_schema=ChatContext)
    builder.add_node(WRITING_COACH_NODE, writing_coach)
    builder.add_edge(START, WRITING_COACH_NODE)
    builder.add_edge(WRITING_COACH_NODE, END)
    return builder.compile(checkpointer=False)


def _reading_coach_graph() -> CompiledStateGraph[ChatState, ChatContext, ChatState, ChatState]:
    builder = StateGraph(ChatState, context_schema=ChatContext)
    builder.add_node(READING_COACH_NODE, reading_coach)
    builder.add_edge(START, READING_COACH_NODE)
    builder.add_edge(READING_COACH_NODE, END)
    return builder.compile(checkpointer=False)


def _speaking_coach_graph() -> CompiledStateGraph[ChatState, ChatContext, ChatState, ChatState]:
    builder = StateGraph(ChatState, context_schema=ChatContext)
    builder.add_node(SPEAKING_COACH_NODE, speaking_coach)
    builder.add_edge(START, SPEAKING_COACH_NODE)
    builder.add_edge(SPEAKING_COACH_NODE, END)
    return builder.compile(checkpointer=False)


def build_chat_graph(checkpointer: BaseCheckpointSaver[Any]) -> ChatGraph:
    """START -> load_context -> supervisor -> a coach -> END (ADR 0023 §2); the tutor's
    follow-ups after it (ADR 0064). Coaches are subgraphs on the same thread: they read
    and extend one history.

    Coaches never checkpoint on their own (`checkpointer=False`): a subgraph that does
    stores its input, untracked learner context and practice guidance included, which
    must never reach the checkpoint. The parent keeps the messages they add.
    """
    builder = StateGraph(
        ChatState,
        context_schema=ChatContext,
        input_schema=StampedMessagesState,
        output_schema=StampedMessagesState,
    )
    builder.add_node(LOAD_CONTEXT_NODE, load_context)
    builder.add_node(SUPERVISOR_NODE, supervisor)
    builder.add_node(TUTOR_NODE, _tutor_graph())
    builder.add_node(GRAMMAR_COACH_NODE, _grammar_coach_graph())
    builder.add_node(WRITING_COACH_NODE, _writing_coach_graph())
    builder.add_node(READING_COACH_NODE, _reading_coach_graph())
    builder.add_node(SPEAKING_COACH_NODE, _speaking_coach_graph())
    builder.add_edge(START, LOAD_CONTEXT_NODE)
    builder.add_edge(LOAD_CONTEXT_NODE, SUPERVISOR_NODE)
    builder.add_node(DEEPEN_NODE, deepen, destinations=(DEEPEN_NODE, END))
    builder.add_edge(TUTOR_NODE, DEEPEN_NODE)
    builder.add_edge(GRAMMAR_COACH_NODE, END)
    builder.add_edge(WRITING_COACH_NODE, END)
    builder.add_edge(READING_COACH_NODE, END)
    builder.add_edge(SPEAKING_COACH_NODE, END)
    return builder.compile(checkpointer=checkpointer)
