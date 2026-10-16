"""Practice set graph (ADR 0021 §3, P2 plan §3.4; per slot since ADR 0048):

    START -> produce -> fill -> save -> END

`produce` runs one pipeline per slot, side by side (at most `practice.parallel_calls`
model calls at a time): `generate` drafts that one slot, code turns the draft into its
format's item (`drafts.to_body`), `critic` reviews it and `drafts.judge` decides; a
rejected or invalid item is written again with the reasons, at most
`practice.max_regenerations` more rounds. An accepted item is handed to
`ExerciseContext.publish` at once, so the learner can start before the set is done.

A set the learner is waiting for has a time budget (`practice.wait_budget_seconds`,
task 49.3): a slot starts no new round that, at the pace of its last one, would end
past it; the bank fills it instead. A set generated ahead has none.

`fill` gives the slots still open (rounds used up, out of time, or a model failed) an
item from the placement bank, drops what the bank cannot fill, and fails the set when
fewer than `practice.min_items` are left (Q33c, Q33d). `save` hands the result to the
context, like the placement graph.

The model calls come in through the context, so tests run the graph with fakes and no
checkpointer is needed: a set is generated in one go, and a process that dies midway
leaves a `generating` set that the service marks failed.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
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

logger = logging.getLogger(__name__)

PRODUCE_NODE: Final = "produce"
FILL_NODE: Final = "fill"
SAVE_NODE: Final = "save"

# `reviewing` is no longer reported (ADR 0048 §1): the slots are at different steps.
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
    # Called with each item as soon as the critic passes it, before the set is done
    # (ADR 0048 §2).
    publish: Callable[[MadeItem], Awaitable[None]] | None = None
    # The learner's candidate weak KCs by priority, for bank items past the set's own
    # KCs (Q33g).
    wider_kcs: Sequence[str] = ()
    # Seconds the learner waits at most, roughly; None: generated ahead, no budget.
    wait_budget: float | None = None
    # A quiz card's set (ADR 0044 §4): its own smallest size instead of
    # practice.min_items, and no bank for understanding checks (the bank is choice4).
    min_items: int | None = None
    use_bank: bool = True
    clock: Callable[[], float] = time.monotonic


class _Candidate(TypedDict):
    body: ExerciseBody
    draft: dict[str, Any]
    difficulty: float
    ratings: dict[str, str]
    model: str | None


class ExerciseState(TypedDict, total=False):
    # By position, the accepted item of each slot that got one.
    accepted: dict[int, MadeItem]
    rejected: list[MadeItem]
    # Slots that ended without an accepted item.
    open: list[int]
    # The last reasons per open slot, for the log of a failed set.
    feedback: dict[int, Rejected]
    # Most rounds any slot took.
    rounds: int
    max_rounds: int
    # Why some model call stopped a slot: an error code, the first one seen.
    model_error: str | None
    result: SetResult


type ExerciseGraph = CompiledStateGraph[
    ExerciseState, ExerciseContext, ExerciseState, ExerciseState
]


def start_state(briefs: Sequence[ItemBrief], rules: Rules) -> ExerciseState:
    return {
        "max_rounds": 1 + rules.practice.max_regenerations,
        "accepted": {},
        "rejected": [],
        "open": [b.position for b in briefs],
        "feedback": {},
        "rounds": 0,
        "model_error": None,
    }


def _error_code(exc: Exception) -> str:
    return exc.code if isinstance(exc, NoModelConfiguredError) else "generation_failed"


async def _report(ctx: ExerciseContext, stage: Stage) -> None:
    if ctx.report is not None:
        await ctx.report(stage)


@dataclass
class _Slot:
    """How one slot's pipeline ended."""

    accepted: MadeItem | None = None
    rejected: list[MadeItem] = field(default_factory=list)
    feedback: Rejected | None = None
    rounds: int = 0
    error: str | None = None


@dataclass
class _Run:
    """What the slots of one set share while they run side by side."""

    ctx: ExerciseContext
    max_rounds: int
    calls: asyncio.Semaphore
    started_at: float
    # Set when a call shows no model can serve this tenant: no slot starts another.
    stop: str | None = None
    rewriting: bool = False

    def out_of_time(self, round_seconds: float) -> bool:
        """Another round of a slot, at the pace of its last one, would end past the
        wait budget (task 49.3)."""
        if self.ctx.wait_budget is None:
            return False
        return self.ctx.clock() - self.started_at + round_seconds > self.ctx.wait_budget

    async def call(
        self, call: StructuredCall, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        async with self.calls:
            return await call(messages, schema)


async def _write(
    run: _Run, brief: ItemBrief, feedback: Rejected | None, rounds: int
) -> tuple[_Candidate, None] | tuple[None, Rejected]:
    """One draft for the slot, turned into its format's item; or why it can't be used.
    Raises when the model call fails."""
    ctx = run.ctx
    reply = await run.call(
        ctx.generate,
        generate_messages(
            [brief], ctx.learner, ctx.rules, {brief.position: feedback} if feedback else None
        ),
        drafts.generated_set_model(ctx.rules, [brief]),
    )
    draft = drafts.by_position(drafts.drafts_in(reply.output, [brief]), [brief.position]).get(
        brief.position
    )
    if draft is None:
        _rejected_unreviewed(brief, rounds, "no draft was written for this position")
        return None, Rejected({}, ["no draft was written for this position"])
    shown = draft.model_dump(exclude={"position", "ratings"}, exclude_none=True)
    rng = random.Random(ctx.seed * 1000 + brief.position * 10 + rounds)
    try:
        body = drafts.to_body(draft, brief, rng)
        value, levels = drafts.difficulty(brief.kc, drafts.ratings_of(draft), ctx.rules)
    except ValueError as exc:  # DraftError, or a rating prior_difficulty rejects
        _rejected_unreviewed(brief, rounds, str(exc))
        return None, Rejected(shown, [f"invalid item: {exc}"])
    candidate: _Candidate = {
        "body": body,
        "draft": shown,
        "difficulty": value,
        "ratings": levels,
        "model": reply.model,
    }
    return candidate, None


async def _review(
    run: _Run, brief: ItemBrief, candidate: _Candidate, rounds: int
) -> tuple[MadeItem | None, Rejected | None]:
    """The critic's item for the slot: accepted (no reasons), rejected (kept, with
    reasons), or not reviewed (None, with reasons). Raises when the model call fails."""
    ctx = run.ctx
    reply = await run.call(
        ctx.critique,
        critic_messages([(brief, candidate["body"])], ctx.learner, ctx.rules),
        drafts.critic_report_model(ctx.rules),
    )
    review = drafts.by_position(drafts.reviews_in(reply.output), [brief.position]).get(
        brief.position
    )
    if review is None:
        # Not reviewed is not rejected: the item is fine as far as anyone knows, so it
        # is written again rather than kept as a critic decision.
        return None, Rejected(candidate["draft"], ["the reviewer skipped it"])
    verdict = drafts.judge(candidate["body"], brief.kc, candidate["difficulty"], review, ctx.rules)
    record = {
        "verdict": "pass" if verdict.ok else "fail",
        "reasons": list(verdict.reasons),
        "problems": list(review.problems),
        "own_answer": review.own_answer,
        "own_segment": review.own_segment,
        "ratings": dict(verdict.ratings),
        "generator_ratings": candidate["ratings"],
        "generator_difficulty": candidate["difficulty"],
        "round": rounds,
        "model": reply.model,
    }
    item = MadeItem(
        position=brief.position,
        kc_id=brief.kc.id,
        format=brief.item.format,
        body=candidate["body"],
        difficulty=verdict.difficulty,
        ratings=verdict.ratings,
        critic=record,
        model=candidate["model"],
    )
    return item, None if verdict.ok else Rejected(candidate["draft"], verdict.reasons)


async def _slot(run: _Run, brief: ItemBrief) -> _Slot:
    """Write, check and review one slot, rewriting it with the reasons until it passes,
    runs out of rounds or time, or a model call fails (ADR 0048 §1)."""
    out = _Slot()
    round_seconds = 0.0
    while out.rounds < run.max_rounds and run.stop is None:
        if out.rounds > 0 and run.out_of_time(round_seconds):
            break
        if out.rounds > 0 and not run.rewriting:
            run.rewriting = True
            await _report(run.ctx, "rewriting")
        began = run.ctx.clock()
        out.rounds += 1
        try:
            candidate, problem = await _write(run, brief, out.feedback, out.rounds - 1)
            if candidate is not None:
                item, problem = await _review(run, brief, candidate, out.rounds)
                if item is not None and problem is None:
                    out.accepted = item
                    if run.ctx.publish is not None:
                        await run.ctx.publish(item)
                    return out
                if item is not None:
                    out.rejected.append(item)
        except Exception as exc:
            logger.warning("exercise slot %d: model call failed", brief.position, exc_info=True)
            out.error = _error_code(exc)
            if isinstance(exc, NoModelConfiguredError):
                run.stop = out.error
            return out
        out.feedback = problem
        round_seconds = run.ctx.clock() - began
    return out


async def produce(state: ExerciseState, runtime: Runtime[ExerciseContext]) -> dict[str, Any]:
    """Every slot's pipeline, side by side; an accepted item is published at once."""
    ctx = runtime.context
    await _report(ctx, "generating")
    run = _Run(
        ctx,
        state["max_rounds"],
        asyncio.Semaphore(ctx.rules.practice.parallel_calls),
        ctx.clock(),
    )
    slots = await asyncio.gather(*(_slot(run, brief) for brief in ctx.briefs))
    accepted = {s.accepted.position: s.accepted for s in slots if s.accepted is not None}
    rejected = [item for s in slots for item in s.rejected]
    open_slots = [b.position for b, s in zip(ctx.briefs, slots, strict=True) if s.accepted is None]
    feedback = {
        b.position: s.feedback
        for b, s in zip(ctx.briefs, slots, strict=True)
        if s.accepted is None and s.feedback is not None
    }
    errors = [s.error for s in slots if s.error is not None]
    return {
        "accepted": accepted,
        "rejected": rejected,
        "open": sorted(open_slots),
        "feedback": feedback,
        "rounds": max((s.rounds for s in slots), default=0),
        "model_error": run.stop or (errors[0] if errors else None),
    }


def _rejected_unreviewed(brief: ItemBrief, rounds: int, reason: str) -> None:
    """Kept only as feedback for the rewrite otherwise, so a set that ends with nothing
    the critic saw could not be told apart from a model outage (task 86.9)."""
    logger.info(
        "exercise draft %d (%s) rejected before review, round %d: %s",
        brief.position,
        brief.item.format,
        rounds + 1,
        reason,
    )


async def fill(state: ExerciseState, runtime: Runtime[ExerciseContext]) -> dict[str, Any]:
    ctx = runtime.context
    accepted = dict(state["accepted"])
    by_position = {b.position: b for b in ctx.briefs}
    if state["open"] and ctx.use_bank:
        await _report(ctx, "filling")
        picks = bank.fill(
            [bank.Slot(p, by_position[p].kc.id) for p in state["open"]],
            neighbours={p: item.kc_id for p, item in accepted.items()},
            weak_kcs=list(dict.fromkeys(b.kc.id for b in ctx.briefs if b.item.role == "weak")),
            wider_kcs=ctx.wider_kcs,
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
    least = ctx.rules.practice.min_items if ctx.min_items is None else ctx.min_items
    failed = len(items) < least
    error = (state["model_error"] or "generation_failed") if failed else None
    if failed:
        logger.warning(
            "exercise set failed: %d of %d items (at least %d), %d rounds, error %s; "
            "still open: %s",
            len(items),
            len(ctx.briefs),
            least,
            state["rounds"],
            error,
            {p: list(r.reasons) for p, r in state["feedback"].items() if p in state["open"]},
        )
    return {"result": SetResult(items, state["rejected"], error, from_bank)}


async def save(state: ExerciseState, runtime: Runtime[ExerciseContext]) -> dict[str, Any]:
    await runtime.context.save(state["result"])
    return {}


def build_exercise_graph() -> ExerciseGraph:
    builder = StateGraph(ExerciseState, context_schema=ExerciseContext)
    builder.add_node(PRODUCE_NODE, produce)
    builder.add_node(FILL_NODE, fill)
    builder.add_node(SAVE_NODE, save)
    builder.add_edge(START, PRODUCE_NODE)
    builder.add_edge(PRODUCE_NODE, FILL_NODE)
    builder.add_edge(FILL_NODE, SAVE_NODE)
    builder.add_edge(SAVE_NODE, END)
    return builder.compile()
