"""Placement test graph (P1 plan §6.2): START -> pick -> ask -> pick ... -> finish -> END.

`pick` works out the next question from the answers so far (`placement.flow`, pure);
`ask` interrupts with the question and records the answer it is resumed with; when
`pick` finds no question left, `finish` computes the result and hands it to the
context's `save`. The checkpoint holds only the seed and the answers, so closing the
page and coming back, or a new process, carries on at the same question.

    config = {"configurable": {"thread_id": str(placement_session.id)}}
    await graph.ainvoke(start_state(seed, difficulties), config, context=ctx)
    answer = {"question_id": "vocab-0", "yes": True}
    await graph.ainvoke(Command(resume=answer), config, context=ctx)

An answer that does not fit the current question is dropped and the same question is
asked again; callers check answers first (`flow.record`) to tell the learner why.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.adaptive.placement import flow
from app.adaptive.placement.flow import AnswerInput, PlacementResult, Progress, Question
from app.adaptive.placement.items import ItemBank
from app.adaptive.placement.words import WordPool
from app.adaptive.rules import Rules

PICK_NODE: Final = "pick"
ASK_NODE: Final = "ask"
FINISH_NODE: Final = "finish"


class WordSource(Protocol):
    async def pool(self) -> WordPool: ...


@dataclass(frozen=True)
class PlacementContext:
    words: WordSource
    bank: ItemBank
    rules: Rules
    # Stores the result (profile, skill estimates, evidence, ...); must be safe to call
    # again with the same result, in case the graph step is re-run.
    save: Callable[[PlacementResult], Awaitable[None]]


class PlacementState(TypedDict):
    progress: Progress
    question: Question | None
    result: PlacementResult | None


type PlacementGraph = CompiledStateGraph[
    PlacementState, PlacementContext, PlacementState, PlacementState
]


def start_state(seed: int, difficulties: Mapping[str, float] | None = None) -> PlacementState:
    return {"progress": flow.new_progress(seed, difficulties), "question": None, "result": None}


async def pick(state: PlacementState, runtime: Runtime[PlacementContext]) -> dict[str, Any]:
    ctx = runtime.context
    question = flow.next_question(state["progress"], await ctx.words.pool(), ctx.bank, ctx.rules)
    return {"question": question}


def after_pick(state: PlacementState) -> Literal["ask", "finish"]:
    return ASK_NODE if state["question"] is not None else FINISH_NODE


async def ask(state: PlacementState, runtime: Runtime[PlacementContext]) -> dict[str, Any]:
    question = state["question"]
    assert question is not None  # routed here only with a question
    answer: AnswerInput = interrupt(flow.public(question))
    try:
        progress = flow.record(state["progress"], question, answer, runtime.context.bank)
    except flow.InvalidAnswerError:
        return {}
    return {"progress": progress}


async def finish(state: PlacementState, runtime: Runtime[PlacementContext]) -> dict[str, Any]:
    ctx = runtime.context
    result = flow.summarize(state["progress"], await ctx.words.pool(), ctx.bank, ctx.rules)
    await ctx.save(result)
    return {"result": result}


def build_placement_graph(checkpointer: BaseCheckpointSaver[Any]) -> PlacementGraph:
    builder = StateGraph(PlacementState, context_schema=PlacementContext)
    builder.add_node(PICK_NODE, pick)
    builder.add_node(ASK_NODE, ask)
    builder.add_node(FINISH_NODE, finish)
    builder.add_edge(START, PICK_NODE)
    builder.add_conditional_edges(PICK_NODE, after_pick, [ASK_NODE, FINISH_NODE])
    builder.add_edge(ASK_NODE, PICK_NODE)
    builder.add_edge(FINISH_NODE, END)
    return builder.compile(checkpointer=checkpointer)
