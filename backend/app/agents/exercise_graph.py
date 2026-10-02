"""Practice set graph (ADR 0021 §3, P2 plan §3.4):

    START -> generate -> critic -> (generate again, at most practice.max_regenerations
             more rounds) -> fill -> save -> END

`generate` drafts every slot still open in one structured call; code turns each draft
into its format's item (`drafts.to_body`). `critic` reviews the new items in one call
and `drafts.judge` decides; a rejected item goes back to `generate` with the reasons.
`fill` gives the slots still open after the last round (or after a model failed) an
item from the placement bank, drops what the bank cannot fill, and fails the set when
fewer than `practice.min_items` are left (Q33c, Q33d). `save` hands the result to the
context, like the placement graph.

The model calls come in through the context, so tests run the graph with fakes and no
checkpointer is needed: a set is generated in one go, and a process that dies midway
leaves a `generating` set that the service marks failed.
"""

import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel

from app.adaptive.exercise import bank, drafts
from app.adaptive.exercise.formats import ExerciseBody, Format
from app.adaptive.exercise.inputs import ItemBrief, LearnerInputs
from app.adaptive.exercise.messages import Rejected, critic_messages, generate_messages
from app.adaptive.kc.catalog import GrammarCatalog
from app.adaptive.placement.items import ItemBank
from app.adaptive.rules import Rules
from app.providers.errors import NoModelConfiguredError

GENERATE_NODE: Final = "generate"
CRITIC_NODE: Final = "critic"
FILL_NODE: Final = "fill"
SAVE_NODE: Final = "save"

type Stage = Literal["generating", "reviewing", "rewriting", "filling"]


@dataclass(frozen=True, slots=True)
class ModelReply:
    output: BaseModel
    # "<connection>:<model>" that answered, after any fallback; None if unknown.
    model: str | None


# A structured call: messages and the output schema in, the parsed output out.
type StructuredCall = Callable[[Sequence[BaseMessage], type[BaseModel]], Awaitable[ModelReply]]


@dataclass(frozen=True, slots=True)
class MadeItem:
    """An item for the set, or one the critic rejected (kept to evaluate the critic)."""

    position: int
    kc_id: str
    format: Format
    body: ExerciseBody
    difficulty: float
    ratings: Mapping[str, str]
    # The critic's verdict, reasons and own answer; None for bank items.
    critic: Mapping[str, Any] | None
    # Who wrote it; None for bank items.
    model: str | None = None
    bank_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class SetResult:
    # By position, the slot in the plan; a slot nothing could fill is left out, so
    # positions may have gaps. Rejected items keep the slot they were written for.
    items: list[MadeItem]
    rejected: list[MadeItem]
    # Set when the set failed: too few items even with the bank.
    error_code: str | None
    # Bank items stand in for some or all slots: the page says so (Q33d).
    from_bank: int = 0


@dataclass(frozen=True)
class ExerciseContext:
    generate: StructuredCall
    critique: StructuredCall
    learner: LearnerInputs
    briefs: Sequence[ItemBrief]
    catalog: GrammarCatalog
    rules: Rules
    bank: ItemBank
    # When the learner last saw each bank item.
    seen: Mapping[str, datetime]
    now: datetime
    seed: int
    save: Callable[[SetResult], Awaitable[None]]
    report: Callable[[Stage], Awaitable[None]] | None = None


class _Candidate(TypedDict):
    body: ExerciseBody
    draft: dict[str, Any]
    difficulty: float
    ratings: dict[str, str]
    model: str | None


class ExerciseState(TypedDict, total=False):
    # Slots still without an accepted item.
    open: list[int]
    # Items waiting for the critic, by position.
    candidates: dict[int, _Candidate]
    accepted: dict[int, MadeItem]
    # The latest rejection per open slot, sent back with the next generate call.
    feedback: dict[int, Rejected]
    rejected: list[MadeItem]
    rounds: int
    # 1 + practice.max_regenerations.
    max_rounds: int
    # Why the model calls stopped: an error code; the open slots go to the bank.
    model_error: str | None
    result: SetResult


type ExerciseGraph = CompiledStateGraph[
    ExerciseState, ExerciseContext, ExerciseState, ExerciseState
]


def start_state(briefs: Sequence[ItemBrief], rules: Rules) -> ExerciseState:
    return {
        "max_rounds": 1 + rules.practice.max_regenerations,
        "open": [b.position for b in briefs],
        "candidates": {},
        "accepted": {},
        "feedback": {},
        "rejected": [],
        "rounds": 0,
        "model_error": None,
    }


def _error_code(exc: Exception) -> str:
    return exc.code if isinstance(exc, NoModelConfiguredError) else "generation_failed"


async def _report(ctx: ExerciseContext, stage: Stage) -> None:
    if ctx.report is not None:
        await ctx.report(stage)


async def generate(state: ExerciseState, runtime: Runtime[ExerciseContext]) -> dict[str, Any]:
    ctx = runtime.context
    rounds = state["rounds"]
    await _report(ctx, "generating" if rounds == 0 else "rewriting")
    by_position = {b.position: b for b in ctx.briefs}
    wanted = [by_position[p] for p in state["open"]]
    feedback = {p: r for p, r in state["feedback"].items() if p in state["open"]}
    try:
        reply = await ctx.generate(
            generate_messages(wanted, ctx.learner, ctx.rules, feedback or None),
            drafts.generated_set_model(ctx.rules),
        )
    except Exception as exc:
        return {"model_error": _error_code(exc), "rounds": rounds + 1}
    found = drafts.by_position(drafts.drafts_in(reply.output), [b.position for b in wanted])
    rng = random.Random(ctx.seed * 1000 + rounds)
    candidates: dict[int, _Candidate] = {}
    new_feedback = dict(state["feedback"])
    for brief in wanted:
        draft = found.get(brief.position)
        if draft is None:
            new_feedback[brief.position] = Rejected({}, ["no draft was written for this position"])
            continue
        shown = draft.model_dump(exclude={"position", "ratings"}, exclude_none=True)
        try:
            body = drafts.to_body(draft, brief, rng)
            value, levels = drafts.difficulty(brief.kc, drafts.ratings_of(draft), ctx.rules)
        except ValueError as exc:  # DraftError, or a rating prior_difficulty rejects
            new_feedback[brief.position] = Rejected(shown, [f"invalid item: {exc}"])
            continue
        candidates[brief.position] = {
            "body": body,
            "draft": shown,
            "difficulty": value,
            "ratings": levels,
            "model": reply.model,
        }
    return {"candidates": candidates, "feedback": new_feedback, "rounds": rounds + 1}


async def critic(state: ExerciseState, runtime: Runtime[ExerciseContext]) -> dict[str, Any]:
    ctx = runtime.context
    candidates = state["candidates"]
    if not candidates:
        return {}
    await _report(ctx, "reviewing")
    by_position = {b.position: b for b in ctx.briefs}
    reviewed = [(by_position[p], c["body"]) for p, c in sorted(candidates.items())]
    try:
        reply = await ctx.critique(
            critic_messages(reviewed, ctx.learner, ctx.rules),
            drafts.critic_report_model(ctx.rules),
        )
    except Exception as exc:
        # Unreviewed items never reach the learner: their slots stay open for the bank.
        return {"candidates": {}, "model_error": _error_code(exc)}
    reviews = drafts.by_position(drafts.reviews_in(reply.output), sorted(candidates))
    accepted = dict(state["accepted"])
    feedback = dict(state["feedback"])
    rejected = list(state["rejected"])
    still_open = [p for p in state["open"] if p not in candidates]
    for position, candidate in sorted(candidates.items()):
        brief = by_position[position]
        review = reviews.get(position)
        if review is None:
            # Not reviewed is not rejected: the item is fine as far as anyone knows,
            # so it is written again rather than kept as a critic decision.
            feedback[position] = Rejected(candidate["draft"], ["the reviewer skipped it"])
            still_open.append(position)
            continue
        verdict = drafts.judge(
            candidate["body"], brief.kc, candidate["difficulty"], review, ctx.rules
        )
        record = {
            "verdict": "pass" if verdict.ok else "fail",
            "reasons": list(verdict.reasons),
            "problems": list(review.problems),
            "own_answer": review.own_answer,
            "own_segment": review.own_segment,
            "ratings": dict(verdict.ratings),
            "generator_ratings": candidate["ratings"],
            "generator_difficulty": candidate["difficulty"],
            "round": state["rounds"],
            "model": reply.model,
        }
        item = MadeItem(
            position=position,
            kc_id=brief.kc.id,
            format=brief.item.format,
            body=candidate["body"],
            difficulty=verdict.difficulty,
            ratings=verdict.ratings,
            critic=record,
            model=candidate["model"],
        )
        if verdict.ok:
            accepted[position] = item
            feedback.pop(position, None)
        else:
            rejected.append(item)
            feedback[position] = Rejected(candidate["draft"], verdict.reasons)
            still_open.append(position)
    return {
        "accepted": accepted,
        "feedback": feedback,
        "rejected": rejected,
        "candidates": {},
        "open": sorted(still_open),
    }


def after_critic(state: ExerciseState) -> str:
    if state["open"] and state["model_error"] is None and state["rounds"] < state["max_rounds"]:
        return GENERATE_NODE
    return FILL_NODE


async def fill(state: ExerciseState, runtime: Runtime[ExerciseContext]) -> dict[str, Any]:
    ctx = runtime.context
    accepted = dict(state["accepted"])
    by_position = {b.position: b for b in ctx.briefs}
    if state["open"]:
        await _report(ctx, "filling")
        picks = bank.fill(
            [bank.Slot(p, by_position[p].kc.id) for p in state["open"]],
            neighbours={p: item.kc_id for p, item in accepted.items()},
            weak_kcs=list(dict.fromkeys(b.kc.id for b in ctx.briefs if b.item.role == "weak")),
            bank=ctx.bank,
            seen=ctx.seen,
            ability=ctx.learner.ability,
            now=ctx.now,
            rules=ctx.rules,
        )
        rng = random.Random(ctx.seed)
        for position, source in picks.items():
            kc = ctx.catalog.get(source.kc)
            assert kc is not None  # the bank is checked against the catalog on load
            accepted[position] = MadeItem(
                position=position,
                kc_id=kc.id,
                format="choice4",
                body=bank.to_body(source, kc, ctx.learner.explain_in, rng),
                difficulty=source.difficulty,
                ratings=source.ratings,
                critic=None,
                bank_item_id=source.id,
            )
    items = [accepted[p] for p in sorted(accepted)]
    from_bank = sum(1 for item in items if item.bank_item_id is not None)
    failed = len(items) < ctx.rules.practice.min_items
    error = (state["model_error"] or "generation_failed") if failed else None
    return {"result": SetResult(items, state["rejected"], error, from_bank)}


async def save(state: ExerciseState, runtime: Runtime[ExerciseContext]) -> dict[str, Any]:
    await runtime.context.save(state["result"])
    return {}


def build_exercise_graph() -> ExerciseGraph:
    builder = StateGraph(ExerciseState, context_schema=ExerciseContext)
    builder.add_node(GENERATE_NODE, generate)
    builder.add_node(CRITIC_NODE, critic)
    builder.add_node(FILL_NODE, fill)
    builder.add_node(SAVE_NODE, save)
    builder.add_edge(START, GENERATE_NODE)
    builder.add_edge(GENERATE_NODE, CRITIC_NODE)
    builder.add_conditional_edges(CRITIC_NODE, after_critic, [GENERATE_NODE, FILL_NODE])
    builder.add_edge(FILL_NODE, SAVE_NODE)
    builder.add_edge(SAVE_NODE, END)
    return builder.compile()
