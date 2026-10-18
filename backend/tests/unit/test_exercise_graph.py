"""The practice set graph with fake models (ADR 0021 §3, ADR 0048): rounds of one
streamed generate call, each draft reviewed as soon as it is written; then bank → save."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.adaptive.exercise.formats import Format
from app.adaptive.exercise.inputs import ItemBrief, LearnerInputs, OwnSentence
from app.adaptive.exercise.planner import PlannedItem
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.placement.items import get_item_bank
from app.adaptive.rules import get_rules
from app.agents.exercise_graph import (
    ExerciseContext,
    MadeItem,
    ModelReply,
    SetResult,
    Stage,
    Written,
    build_exercise_graph,
    start_state,
)
from app.providers.errors import NoModelConfiguredError

CATALOG, RULES, BANK = get_grammar_catalog(), get_rules(), get_item_bank()
NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
GRAPH = build_exercise_graph()
MIDDLE = {
    "vocabulary": "at_target",
    "syntax": "moderate",
    "cues": "partial",
    "distractors": "one_plausible",
}
HARD = {
    "vocabulary": "above_target",
    "syntax": "complex",
    "cues": "none",
    "distractors": "several_plausible",
}
FORMATS: tuple[Format, ...] = (
    "choice4",
    "cloze",
    "find_fix",
    "transform",
    "translate",
    "rewrite_own",
)
# KCs that have bank items, one per slot.
KCS = sorted({item.kc for item in BANK.items})[:6]
OWN = OwnSentence(7, "She like tea.", "She likes tea.")
DRAFTS: dict[Format, dict[str, Any]] = {
    "choice4": {
        "stem": "My brother ___ in a hospital.",
        "options": ["works", "work", "working", "is work"],
        "other_fillings": ["work: my brother is one person"],
        "correct": "works",
    },
    "cloze": {
        "stem": "She ___ coffee.",
        "hint": "drink",
        "other_fillings": ["drank: a habit"],
        "accepted": ["drinks"],
    },
    "find_fix": {
        "segments": ["He ", "go ", "to work."],
        "error_kind": "form",
        "wrong_segment": 1,
        "accepted": ["goes "],
    },
    "transform": {
        "instruction": "Use 'my sister'.",
        "source": "I play tennis.",
        "accepted": ["My sister plays tennis."],
    },
    "translate": {"source": "她走路上班。", "accepted": ["She walks to work."]},
    "rewrite_own": {"instruction": "Correct it.", "accepted": ["She likes tea."]},
    "concept_choice": {
        "question": "Why 'works'?",
        "options": ["one person", "past", "a question", "both"],
        "correct": "one person",
    },
    "explain": {"question": "When does a verb take -s?", "key_points": ["he, she, it"]},
}
KEYS: dict[Format, tuple[str, int | None]] = {
    "choice4": ("works", None),
    "cloze": ("drinks", None),
    "find_fix": ("goes ", 1),
    "transform": ("My sister plays tennis.", None),
    "translate": ("She walks to work.", None),
    "rewrite_own": ("She likes tea.", None),
    "concept_choice": ("one person", None),
    "explain": ("", None),
}


def briefs(n: int = 6) -> list[ItemBrief]:
    out = []
    for position in range(n):
        kc = CATALOG.get(KCS[position])
        assert kc is not None
        fmt = FORMATS[position % len(FORMATS)]
        out.append(
            ItemBrief(
                position,
                PlannedItem(kc.id, fmt, 0.0, "weak"),
                kc,
                OWN if fmt == "rewrite_own" else None,
            )
        )
    return out


LEARNER = LearnerInputs("A2", -1.0, {}, {KCS[5]: OWN}, {}, [])


def section(messages: Sequence[BaseMessage], title: str) -> list[dict[str, Any]]:
    content = messages[-1].content
    assert isinstance(content, str)
    start = content.index(title) + len(title)
    end = content.find("\n\n", start)
    return json.loads(content[start : end if end != -1 else None])


@dataclass
class FakeModels:
    """Valid drafts for every slot asked; the critic solves closed items as the key
    does. `bad` lists (round, position) the critic rejects, `invalid` the drafts that
    break their format; rounds count per slot, from 0. `generate_error` fails the
    generate calls before they write anything; `cut_after` makes them fail after
    writing that many drafts' worth (the last one cut off)."""

    bad: set[tuple[int, int]] = field(default_factory=set)
    invalid: set[tuple[int, int]] = field(default_factory=set)
    generate_error: Exception | None = None
    cut_after: int | None = None
    # Seconds the generate call takes per draft.
    write_seconds: float = 0
    critic_error: Exception | None = None
    generated: list[list[int]] = field(default_factory=list)
    reviewed: list[list[int]] = field(default_factory=list)
    # By position, the prompts of its generate calls.
    prompts: dict[int, list[str]] = field(default_factory=dict)
    # Positions handed to `publish`, in order.
    published: list[int] = field(default_factory=list)
    # Model calls running at once, the most seen.
    running: int = 0
    most_running: int = 0
    # A generate call is streaming; reviews made meanwhile.
    writing: bool = False
    reviewed_while_writing: int = 0

    async def _busy(self, seconds: float = 0) -> None:
        self.running += 1
        self.most_running = max(self.most_running, self.running)
        await asyncio.sleep(seconds)  # let the other calls in
        self.running -= 1

    def rounds_of(self, position: int) -> int:
        return sum(position in g for g in self.generated)

    async def generate(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> AsyncIterator[Written]:
        asked = section(messages, "Items to write:\n")
        await self._busy()
        if self.generate_error is not None:
            raise self.generate_error
        (rounds,) = {self.rounds_of(a["position"]) for a in asked}
        self.generated.append([a["position"] for a in asked])
        for a in asked:
            self.prompts.setdefault(a["position"], []).append(str(messages[-1].content))
        items = {}
        for a in asked:
            fmt = a["format"]
            data = {**DRAFTS[fmt]}
            if (rounds, a["position"]) in self.invalid:
                data["accepted"] = None
                data["correct"] = "none of them"
            items[f"item_{a['position']}"] = {
                "explanation": "Because.",
                **data,
            }
        schema.model_validate(items)
        # One draft at a time, as a model writes the set (keys in order).
        self.writing = True
        try:
            written: dict[str, Any] = {}
            for n, (key, value) in enumerate(items.items()):
                if n == self.cut_after:
                    raise RuntimeError("connection reset")
                written[key] = value
                yield Written(dict(written), "fake:writer")
                await asyncio.sleep(self.write_seconds)
            yield Written(dict(written), "fake:writer", done=True)
        finally:
            self.writing = False

    async def critique(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        items = section(messages, "Items to review:\n")
        self.reviewed_while_writing += self.writing
        await self._busy(0.002)
        if self.critic_error is not None:
            raise self.critic_error
        (rounds,) = {self.rounds_of(i["position"]) - 1 for i in items}
        self.reviewed.append([i["position"] for i in items])
        reviews = []
        for i in items:
            answer, segment = KEYS[i["format"]]
            bad = (rounds, i["position"]) in self.bad
            reviews.append(
                {
                    "position": i["position"],
                    "own_answer": answer,
                    "own_segment": segment,
                    "answer_ok": not bad,
                    "tests_kc": True,
                    "content_ok": True,
                    "problems": ["Two options fit."] if bad else [],
                    "ratings": {k: {"level": v, "reason": "r"} for k, v in MIDDLE.items()},
                }
            )
        return ModelReply(schema.model_validate({"reviews": reviews}), "fake:critic")


async def run(
    models: FakeModels,
    n: int = 6,
    seen: dict[str, datetime] | None = None,
    *,
    wait_budget: float | None = None,
    tick: float = 0.0,
    min_items: int | None = None,
    on_publish: Callable[[MadeItem], Awaitable[None]] | None = None,
) -> tuple[SetResult, list[Stage]]:
    """`tick`: seconds the fake clock moves on each time it is read."""
    now = [0.0]

    def clock() -> float:
        now[0] += tick
        return now[0]

    saved: list[SetResult] = []
    stages: list[Stage] = []

    async def save(result: SetResult) -> None:
        saved.append(result)

    async def publish(item: MadeItem) -> None:
        assert not saved, "published after the set was saved"
        models.published.append(item.position)
        if on_publish is not None:
            await on_publish(item)

    async def report(stage: Stage) -> None:
        stages.append(stage)

    planned = briefs(n)
    ctx = ExerciseContext(
        generate=models.generate,
        critique=models.critique,
        learner=LEARNER,
        briefs=planned,
        catalog=CATALOG,
        rules=RULES,
        bank=BANK,
        seen=seen or {},
        now=NOW,
        seed=3,
        save=save,
        report=report,
        publish=publish,
        wait_budget=wait_budget,
        min_items=min_items,
        clock=clock,
    )
    await GRAPH.ainvoke(start_state(planned, RULES), context=ctx)
    (result,) = saved
    return result, stages


async def test_all_items_pass_first_time() -> None:
    models = FakeModels()

    result, stages = await run(models)

    assert result.error_code is None and result.from_bank == 0 and result.rejected == []
    assert [i.position for i in result.items] == list(range(6))
    assert [i.format for i in result.items] == list(FORMATS)
    assert [i.kc_id for i in result.items] == KCS
    assert all(i.model == "fake:writer" and i.critic is not None for i in result.items)
    first = result.items[0].critic
    assert first is not None
    assert first["verdict"] == "pass" and first["model"] == "fake:critic"
    assert result.items[0].ratings == MIDDLE
    rewrite = result.items[5].body
    assert rewrite.content.evidence_id == OWN.evidence_id  # type: ignore[union-attr]
    # One call writes the set; each item is reviewed on its own.
    assert models.generated == [list(range(6))]
    assert sorted(models.reviewed) == [[p] for p in range(6)]
    assert sorted(models.published) == list(range(6))
    assert stages == ["generating"]


async def test_items_are_reviewed_and_published_while_the_set_is_written() -> None:
    models = FakeModels(write_seconds=0.01)  # a review takes 0.002 s
    published_while_writing: list[int] = []

    async def note(item: MadeItem) -> None:
        if models.writing:
            published_while_writing.append(item.position)

    result, _ = await run(models, on_publish=note)

    assert models.reviewed_while_writing >= 1
    assert published_while_writing and published_while_writing[0] == 0
    assert len(result.items) == 6


async def test_only_rejected_items_are_rewritten_with_the_reasons() -> None:
    models = FakeModels(bad={(0, 2)})

    result, stages = await run(models)

    # Round 2 writes slot 2 only.
    assert models.generated == [list(range(6)), [2]]
    assert models.reviewed.count([2]) == 2
    assert "Two options fit." in models.prompts[2][1] and "rejected" in models.prompts[2][1]
    assert result.error_code is None and len(result.items) == 6 and result.from_bank == 0
    (rejected,) = result.rejected
    assert rejected.position == 2 and rejected.critic is not None
    assert rejected.critic["verdict"] == "fail" and rejected.critic["round"] == 1
    assert "Two options fit." in rejected.critic["reasons"]
    assert result.items[2].critic["round"] == 2  # type: ignore[index]
    # The others did not wait for slot 2.
    assert models.published[-1] == 2
    assert stages == ["generating", "rewriting"]


async def test_invalid_drafts_are_rewritten_without_reaching_the_critic() -> None:
    models = FakeModels(invalid={(0, 0), (0, 1)})

    result, _ = await run(models)

    assert sorted(models.reviewed) == [[p] for p in range(6)]  # never the invalid drafts
    assert models.generated == [list(range(6)), [0, 1]]
    assert "invalid item" in models.prompts[0][1]
    assert len(result.items) == 6 and result.rejected == []


async def test_items_failing_every_round_go_to_the_bank() -> None:
    rounds = 1 + RULES.practice.max_regenerations
    models = FakeModels(bad={(r, 1) for r in range(rounds)})

    result, stages = await run(models)

    assert models.generated[1:] == [[1]] * (rounds - 1)
    assert len(result.rejected) == rounds
    assert result.error_code is None and result.from_bank == 1
    assert 1 not in models.published
    item = result.items[1]
    assert item.bank_item_id is not None and item.critic is None and item.model is None
    assert item.format == "choice4" and item.kc_id == KCS[1]
    assert stages[-1] == "filling"


@pytest.mark.parametrize(("budget", "rounds"), [(None, 3), (1000.0, 3), (200.0, 2), (150.0, 1)])
async def test_a_waiting_learner_gets_no_round_past_the_budget(
    budget: float | None, rounds: int
) -> None:
    # One slot, 40 s a clock read: the set starts at 40, each round reads the clock as
    # it starts (80) and ends (120, 40 s long), and before a rewrite once more: the
    # check before round 2 sees 160 - 40 + 40 = 160 s, before round 3 280 s.
    assert 1 + RULES.practice.max_regenerations == 3
    models = FakeModels(bad={(r, 0) for r in range(3)})

    result, stages = await run(models, n=1, wait_budget=budget, tick=40.0, min_items=1)

    assert models.generated.count([0]) == rounds
    assert len(result.rejected) == rounds
    assert result.error_code is None and result.from_bank == 1
    assert result.items[0].bank_item_id is not None and stages[-1] == "filling"


async def test_a_failing_model_leaves_the_set_to_the_bank() -> None:
    models = FakeModels(generate_error=RuntimeError("vendor down"))

    result, _ = await run(models)

    assert result.error_code is None
    assert result.from_bank == 6 and all(i.format == "choice4" for i in result.items)
    assert [i.kc_id for i in result.items] == KCS


async def test_unreviewed_items_never_reach_the_learner() -> None:
    models = FakeModels(critic_error=RuntimeError("vendor down"))

    result, _ = await run(models)

    assert result.from_bank == 6 and result.rejected == [] and models.published == []
    assert models.generated == [list(range(6))]  # a failed review is not written again


async def test_too_few_items_fail_the_set_with_the_model_error() -> None:
    error = NoModelConfiguredError("llm", "exercise_generate", [])
    seen = {item.id: NOW for item in BANK.items}  # all seen today: nothing to fill with

    result, _ = await run(FakeModels(generate_error=error), seen=seen)

    assert result.items == [] and result.error_code == "no_llm_configured"


async def test_a_failed_set_logs_why_its_slots_stayed_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Drafts rejected before review left no trace; only a rerun found out why (86.9)."""
    rounds = 1 + RULES.practice.max_regenerations
    models = FakeModels(invalid={(r, p) for r in range(rounds) for p in range(6)})
    seen = {item.id: NOW for item in BANK.items}

    with caplog.at_level("INFO", logger="app.agents.exercise_graph"):
        result, _ = await run(models, seen=seen)

    assert result.items == [] and result.error_code == "generation_failed"
    assert models.reviewed == []
    rejected = [r for r in caplog.records if "rejected before review" in r.getMessage()]
    assert len(rejected) == 6 * rounds
    (failed,) = [r for r in caplog.records if r.levelname == "WARNING"]
    assert "0 of 6 items" in failed.getMessage() and "invalid item" in failed.getMessage()


async def test_dropped_slots_leave_a_gap() -> None:
    rounds = 1 + RULES.practice.max_regenerations
    models = FakeModels(bad={(r, 0) for r in range(rounds)})
    seen = {item.id: NOW for item in BANK.items}

    result, _ = await run(models, seen=seen)

    assert result.error_code is None
    assert [i.position for i in result.items] == list(range(1, 6))
    assert [i.kc_id for i in result.items] == KCS[1:]


async def test_a_critic_rating_far_from_the_target_is_kept_not_rejected() -> None:
    """ADR 0055 §4: the critic's rating is the item's difficulty; how far it is from the
    planned target is recorded for evaluation only."""
    models = FakeModels()
    original = models.critique

    async def harsh(messages: Sequence[BaseMessage], schema: type[BaseModel]) -> ModelReply:
        reply = await original(messages, schema)
        data = reply.output.model_dump()
        for review in data["reviews"]:
            if review["position"] == 3:
                review["ratings"] = {k: {"level": v, "reason": "r"} for k, v in HARD.items()}
        return ModelReply(schema.model_validate(data), reply.model)

    models.critique = harsh  # type: ignore[method-assign]

    result, _ = await run(models)

    assert models.generated == [list(range(6))]
    assert result.rejected == []
    (item,) = [i for i in result.items if i.position == 3]
    assert item.ratings == HARD
    assert item.critic is not None
    assert item.critic["difficulty_gap"] == pytest.approx(
        item.difficulty - item.critic["target_difficulty"], abs=0.01
    )
    assert "generator_ratings" not in item.critic


async def test_reviews_run_side_by_side_up_to_the_limit() -> None:
    models = FakeModels()

    await run(models, n=6)

    assert models.most_running == RULES.practice.parallel_calls


async def test_a_call_cut_off_midway_keeps_the_drafts_written_before() -> None:
    # Cut while writing the 4th draft: the 3rd was the last one in the args then, maybe
    # cut off too, so only the first two are whole.
    models = FakeModels(cut_after=3)

    result, _ = await run(models)

    assert sorted(models.published) == [0, 1]
    assert models.generated == [list(range(6))]  # no round after a failed call
    assert result.error_code is None and result.from_bank == 4


async def test_no_model_for_the_critic_stops_the_rounds() -> None:
    error = NoModelConfiguredError("llm", "exercise_critic", [])
    models = FakeModels(critic_error=error)

    result, _ = await run(models)

    assert models.generated == [list(range(6))]
    assert models.published == [] and result.from_bank == 6
