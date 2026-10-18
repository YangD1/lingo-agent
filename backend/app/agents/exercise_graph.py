"""Practice set graph (ADR 0021 §3, P2 plan §3.4; streamed since ADR 0048):

    START -> produce -> fill -> save -> END

`produce` runs rounds. Each round is one streamed `generate` call writing every slot
still open; as soon as a slot's draft is written (the next one starts, or the call
ends), code turns it into its format's item (`drafts.to_body`) and `critic` reviews it
on its own, while the rest are still written (at most `practice.parallel_calls` reviews
at a time); `drafts.judge` decides. An accepted item is handed to
`ExerciseContext.publish` at once, so the learner can start before the set is done. The
rejected or invalid slots are written again with the reasons in the next round, at
most `practice.max_regenerations` more rounds.

A set the learner is waiting for has a time budget (`practice.wait_budget_seconds`,
task 49.3): no round starts that, at the pace of the last one, would end past it, and
when it runs out the model calls still going are cancelled (ADR 0048, task 101.4e);
the bank fills the open slots instead. A set generated ahead has none.

The set's calls share one `RetryBudget` (ADR 0056): the provider layer retries a call
that stalls before its first part from it, and when the generate call stalls after
some drafts, `_round` keeps those and asks again for the rest only, from the same
budget, without using up a rewrite round.

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
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, ValidationError

from app.adaptive.exercise import bank, drafts
from app.adaptive.exercise.formats import ExerciseBody, Format
from app.adaptive.exercise.inputs import ItemBrief, LearnerInputs
from app.adaptive.exercise.messages import Rejected, critic_messages, generate_messages
from app.adaptive.kc.catalog import GrammarCatalog
from app.adaptive.placement.items import ItemBank
from app.adaptive.rules import Rules
from app.providers.errors import NoModelConfiguredError
from app.providers.resilience import CallStalledError, RetryBudget

logger = logging.getLogger(__name__)

PRODUCE_NODE: Final = "produce"
FILL_NODE: Final = "fill"
SAVE_NODE: Final = "save"

# Reviews run while the set is written (ADR 0048 §1), so there is no `reviewing` stage.
type Stage = Literal["generating", "rewriting", "filling"]


@dataclass(frozen=True, slots=True)
class ModelReply:
    output: BaseModel
    # "<connection>:<model>" that answered, after any fallback; None if unknown.
    model: str | None


# A structured call: messages and the output schema in, the parsed output out.
type StructuredCall = Callable[[Sequence[BaseMessage], type[BaseModel]], Awaitable[ModelReply]]


@dataclass(frozen=True, slots=True)
class Written:
    """What a streamed structured call has written so far (ADR 0048)."""

    # The output's fields so far, as JSON: the last one may still be cut off.
    args: Mapping[str, Any]
    # "<connection>:<model>" writing it; None if unknown.
    model: str | None = None
    # The call has ended: the last field is whole too.
    done: bool = False


# A streamed structured call: messages and the output schema in, what is written so far
# out, each time it grows.
type StreamedCall = Callable[[Sequence[BaseMessage], type[BaseModel]], AsyncIterator[Written]]


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
    generate: StreamedCall
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
    # Retries the set's calls share (ADR 0056 §4); None: a stalled generate call is not
    # asked again.
    retries: RetryBudget | None = None


class _Candidate(TypedDict):
    body: ExerciseBody
    draft: dict[str, Any]
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
class _Run:
    """One set's rounds: what the slots got so far, shared by the reviews that run side
    by side."""

    ctx: ExerciseContext
    calls: asyncio.Semaphore
    accepted: dict[int, MadeItem] = field(default_factory=dict)
    rejected: list[MadeItem] = field(default_factory=list)
    # The last reasons per slot not accepted, for its rewrite and the log.
    feedback: dict[int, Rejected] = field(default_factory=dict)
    # Slots a failed review ended: not written again, left to the bank.
    closed: set[int] = field(default_factory=set)
    # Why a model call failed: an error code, the first one seen.
    error: str | None = None
    # Set when generating failed, or a call shows no model can serve this tenant: no
    # round starts after this one.
    stop: bool = False
    # Event-loop time the learner's wait budget runs out at; None: no budget.
    deadline: float | None = None

    def failed(self, exc: Exception, *, generating: bool) -> None:
        self.error = self.error or _error_code(exc)
        if generating or isinstance(exc, NoModelConfiguredError):
            self.stop = True

    async def call(
        self, call: StructuredCall, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        scope = asyncio.timeout_at(self.deadline)
        try:
            async with scope, self.calls:
                return await call(messages, schema)
        except TimeoutError:
            if scope.expired():
                raise _OutOfTimeError from None
            raise


class _OutOfTimeError(Exception):
    """The learner's wait budget ran out while a model call was still going."""


def _candidate(
    run: _Run, brief: ItemBrief, raw: Any, model: str | None, rounds: int
) -> tuple[_Candidate, None] | tuple[None, Rejected]:
    """A slot's draft, as written in the streamed set, turned into its format's item; or
    why it can't be used."""
    ctx = run.ctx
    key = f"item_{brief.position}"
    try:
        output = drafts.generated_set_model(ctx.rules, [brief]).model_validate({key: raw})
    except ValidationError as exc:
        reason = f"invalid item: {exc.errors()[0]['msg']}"
        _rejected_unreviewed(brief, rounds, reason)
        return None, Rejected(raw if isinstance(raw, dict) else {}, [reason])
    found = drafts.drafts_in(output, [brief])
    if not found:
        _rejected_unreviewed(brief, rounds, "no draft was written for this position")
        return None, Rejected({}, ["no draft was written for this position"])
    draft = found[0]
    shown = draft.model_dump(exclude={"position"}, exclude_none=True)
    rng = random.Random(ctx.seed * 1000 + brief.position * 10 + rounds)
    try:
        body = drafts.to_body(draft, brief, rng)
    except drafts.DraftError as exc:
        _rejected_unreviewed(brief, rounds, str(exc))
        return None, Rejected(shown, [f"invalid item: {exc}"])
    candidate: _Candidate = {"body": body, "draft": shown, "model": model}
    return candidate, None


async def _review(
    run: _Run, brief: ItemBrief, candidate: _Candidate, rounds: int
) -> tuple[MadeItem | None, Rejected | None]:
    """The critic's item for the slot: accepted (no reasons), rejected (kept, with
    reasons), or not reviewed (None, with reasons). Raises when the model call fails."""
    ctx = run.ctx
    reply = await run.call(
        ctx.critique,
        critic_messages([(brief, candidate["body"])], ctx.rules),
        drafts.critic_report_model(ctx.rules),
    )
    review = drafts.by_position(drafts.reviews_in(reply.output), [brief.position]).get(
        brief.position
    )
    if review is None:
        # Not reviewed is not rejected: the item is fine as far as anyone knows, so it
        # is written again rather than kept as a critic decision.
        return None, Rejected(candidate["draft"], ["the reviewer skipped it"])
    target = brief.item.target_difficulty
    verdict = drafts.judge(candidate["body"], brief.kc, target, review, ctx.rules)
    record = {
        "verdict": "pass" if verdict.ok else "fail",
        "reasons": list(verdict.reasons),
        "problems": list(review.problems),
        "own_answer": review.own_answer,
        "own_segment": review.own_segment,
        "ratings": dict(verdict.ratings),
        "target_difficulty": target,
        "difficulty_gap": verdict.gap,
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


async def _settle(run: _Run, brief: ItemBrief, raw: Any, model: str | None, rounds: int) -> None:
    """Check and review one slot's draft as soon as it is written; publish it once it
    passes, else keep the reasons for the next round."""
    candidate, problem = _candidate(run, brief, raw, model, rounds)
    if candidate is not None:
        try:
            item, problem = await _review(run, brief, candidate, rounds + 1)
        except _OutOfTimeError:
            # Not the model's fault: the bank fills the slot.
            run.closed.add(brief.position)
            return
        except Exception as exc:
            logger.warning("exercise slot %d: review failed", brief.position, exc_info=True)
            run.failed(exc, generating=False)
            run.closed.add(brief.position)
            return
        if item is not None and problem is None:
            run.accepted[brief.position] = item
            run.feedback.pop(brief.position, None)
            if run.ctx.publish is not None:
                await run.ctx.publish(item)
            return
        if item is not None:
            run.rejected.append(item)
    assert problem is not None
    run.feedback[brief.position] = problem


async def _round(run: _Run, wanted: Sequence[ItemBrief], rounds: int) -> None:
    """One streamed generate call for the slots still open; each draft goes to review as
    soon as the next one starts (or the call ends), so items are reviewed, and passed
    ones published, while the rest are still being written (ADR 0048 §1)."""
    ctx = run.ctx
    by_key = {f"item_{b.position}": b for b in wanted}
    settling: list[asyncio.Task[None]] = []
    taken: set[str] = set()

    async def write(briefs: Sequence[ItemBrief]) -> None:
        feedback = {
            b.position: run.feedback[b.position] for b in briefs if b.position in run.feedback
        }
        scope = asyncio.timeout_at(run.deadline)
        try:
            async with scope:
                async for written in ctx.generate(
                    generate_messages(
                        briefs, ctx.learner, ctx.rules, feedback or None, bank=ctx.bank
                    ),
                    drafts.generated_set_model(ctx.rules, briefs),
                ):
                    keys = [k for k in written.args if k in by_key]
                    # The last key may still be written, until the call ends.
                    for key in keys if written.done else keys[:-1]:
                        if key not in taken:
                            taken.add(key)
                            settling.append(
                                asyncio.create_task(
                                    _settle(
                                        run, by_key[key], written.args[key], written.model, rounds
                                    )
                                )
                            )
        except TimeoutError:
            if scope.expired():
                raise _OutOfTimeError from None
            raise

    try:
        pending = list(wanted)
        while True:
            try:
                await write(pending)
                break
            except CallStalledError:
                # The drafts written so far are reviewed; only the rest is asked again.
                pending = [b for b in pending if f"item_{b.position}" not in taken]
                if not pending or ctx.retries is None or not ctx.retries.take():
                    raise
                logger.warning(
                    "exercise generation stalled after %d drafts: asking again for %d",
                    len(taken),
                    len(pending),
                )
        for key, brief in by_key.items():
            if key not in taken:
                _rejected_unreviewed(brief, rounds, "no draft was written for this position")
                run.feedback[brief.position] = Rejected(
                    {}, ["no draft was written for this position"]
                )
    except _OutOfTimeError:
        logger.warning(
            "exercise set out of time: %d drafts written, bank fills the rest", len(taken)
        )
        run.stop = True
    except Exception as exc:
        # The drafts already written are still reviewed; the rest go to the bank.
        logger.warning("exercise generation call failed", exc_info=True)
        run.failed(exc, generating=True)
    finally:
        await asyncio.gather(*settling)


async def produce(state: ExerciseState, runtime: Runtime[ExerciseContext]) -> dict[str, Any]:
    """Rounds of one streamed generate call each, reviewing drafts as they are written;
    the slots not accepted are written again with the reasons."""
    ctx = runtime.context
    run = _Run(ctx, asyncio.Semaphore(ctx.rules.practice.parallel_calls))
    if ctx.wait_budget is not None:
        run.deadline = asyncio.get_running_loop().time() + ctx.wait_budget
    started_at = ctx.clock()
    wanted = list(ctx.briefs)
    rounds = 0
    last_round = 0.0
    while wanted and rounds < state["max_rounds"] and not run.stop:
        if rounds > 0:
            # Another round, at the pace of the last one, would end past the budget.
            now = ctx.clock()
            if ctx.wait_budget is not None and now - started_at + last_round > ctx.wait_budget:
                break
        await _report(ctx, "generating" if rounds == 0 else "rewriting")
        began = ctx.clock()
        await _round(run, wanted, rounds)
        rounds += 1
        last_round = ctx.clock() - began
        wanted = [
            b for b in wanted if b.position not in run.accepted and b.position not in run.closed
        ]
    open_slots = sorted(b.position for b in ctx.briefs if b.position not in run.accepted)
    return {
        "accepted": dict(run.accepted),
        "rejected": list(run.rejected),
        "open": open_slots,
        "feedback": {p: r for p, r in run.feedback.items() if p in open_slots},
        "rounds": rounds,
        "model_error": run.error,
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
