"""The practice set graph with fake models (ADR 0021 §3): generate → critic → rewrite →
bank → save."""

import json
from collections.abc import Sequence
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
    ModelReply,
    SetResult,
    Stage,
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
        "correct": "works",
    },
    "cloze": {"stem": "She ___ coffee.", "hint": "drink", "accepted": ["drinks"]},
    "find_fix": {"segments": ["He ", "go ", "to work."], "wrong_segment": 1, "accepted": ["goes "]},
    "transform": {
        "instruction": "Use 'my sister'.",
        "source": "I play tennis.",
        "accepted": ["My sister plays tennis."],
    },
    "translate": {"source": "她走路上班。", "accepted": ["She walks to work."]},
    "rewrite_own": {"instruction": "Correct it.", "accepted": ["She likes tea."]},
}
KEYS: dict[Format, tuple[str, int | None]] = {
    "choice4": ("works", None),
    "cloze": ("drinks", None),
    "find_fix": ("goes ", 1),
    "transform": ("My sister plays tennis.", None),
    "translate": ("She walks to work.", None),
    "rewrite_own": ("She likes tea.", None),
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
    break their format, `skip` positions the generator leaves out."""

    bad: set[tuple[int, int]] = field(default_factory=set)
    invalid: set[tuple[int, int]] = field(default_factory=set)
    generate_error: Exception | None = None
    critic_error: Exception | None = None
    generated: list[list[int]] = field(default_factory=list)
    reviewed: list[list[int]] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    async def generate(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        if self.generate_error is not None:
            raise self.generate_error
        asked = section(messages, "Items to write:\n")
        rounds = len(self.generated)
        self.generated.append([a["position"] for a in asked])
        self.prompts.append(str(messages[-1].content))
        items = []
        for a in asked:
            fmt = a["format"]
            data = {**DRAFTS[fmt]}
            if (rounds, a["position"]) in self.invalid:
                data["accepted"] = None
                data["correct"] = "none of them"
            items.append(
                {
                    "position": a["position"],
                    "format": fmt,
                    "explanation": "Because.",
                    "ratings": {k: {"level": v, "reason": "r"} for k, v in MIDDLE.items()},
                    **data,
                }
            )
        return ModelReply(schema.model_validate({"items": items}), "fake:writer")

    async def critique(
        self, messages: Sequence[BaseMessage], schema: type[BaseModel]
    ) -> ModelReply:
        if self.critic_error is not None:
            raise self.critic_error
        items = section(messages, "Items to review:\n")
        rounds = len(self.generated) - 1
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
        wait_budget=wait_budget,
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
    assert models.generated == [list(range(6))] and models.reviewed == [list(range(6))]
    assert stages == ["generating", "reviewing"]


async def test_only_rejected_items_are_rewritten_with_the_reasons() -> None:
    models = FakeModels(bad={(0, 2)})

    result, stages = await run(models)

    assert models.generated == [list(range(6)), [2]]
    assert models.reviewed == [list(range(6)), [2]]
    assert "Two options fit." in models.prompts[1] and "rejected" in models.prompts[1]
    assert result.error_code is None and len(result.items) == 6 and result.from_bank == 0
    (rejected,) = result.rejected
    assert rejected.position == 2 and rejected.critic is not None
    assert rejected.critic["verdict"] == "fail"
    assert "Two options fit." in rejected.critic["reasons"]
    assert stages == ["generating", "reviewing", "rewriting", "reviewing"]


async def test_invalid_drafts_are_rewritten_without_reaching_the_critic() -> None:
    models = FakeModels(invalid={(0, 0), (0, 1)})

    result, _ = await run(models)

    assert models.reviewed[0] == [2, 3, 4, 5]
    assert models.generated[1] == [0, 1]
    assert "invalid item" in models.prompts[1]
    assert len(result.items) == 6 and result.rejected == []


async def test_items_failing_every_round_go_to_the_bank() -> None:
    rounds = 1 + RULES.practice.max_regenerations
    models = FakeModels(bad={(r, 1) for r in range(rounds)})

    result, stages = await run(models)

    assert len(models.generated) == rounds
    assert len(result.rejected) == rounds
    assert result.error_code is None and result.from_bank == 1
    item = result.items[1]
    assert item.bank_item_id is not None and item.critic is None and item.model is None
    assert item.format == "choice4" and item.kc_id == KCS[1]
    assert stages[-1] == "filling"


@pytest.mark.parametrize(("budget", "rounds"), [(None, 3), (1000.0, 3), (150.0, 2), (50.0, 1)])
async def test_a_waiting_learner_gets_no_round_past_the_budget(
    budget: float | None, rounds: int
) -> None:
    # The clock is read once as a round starts and once as its review ends: 40 s a read
    # makes each round 40 s long, and the n-th round end at 80n - 40 s.
    assert 1 + RULES.practice.max_regenerations == 3
    models = FakeModels(bad={(r, 1) for r in range(3)})

    result, stages = await run(models, wait_budget=budget, tick=40.0)

    assert len(models.generated) == rounds
    assert len(result.rejected) == rounds
    assert result.error_code is None and result.from_bank == 1
    assert result.items[1].bank_item_id is not None and stages[-1] == "filling"


async def test_a_failing_model_leaves_the_set_to_the_bank() -> None:
    models = FakeModels(generate_error=RuntimeError("vendor down"))

    result, _ = await run(models)

    assert result.error_code is None
    assert result.from_bank == 6 and all(i.format == "choice4" for i in result.items)
    assert [i.kc_id for i in result.items] == KCS


async def test_unreviewed_items_never_reach_the_learner() -> None:
    models = FakeModels(critic_error=RuntimeError("vendor down"))

    result, _ = await run(models)

    assert result.from_bank == 6 and result.rejected == []
    assert len(models.generated) == 1  # no retry after a model failure


async def test_too_few_items_fail_the_set_with_the_model_error() -> None:
    error = NoModelConfiguredError("llm", "exercise_generate", [])
    seen = {item.id: NOW for item in BANK.items}  # all seen today: nothing to fill with

    result, _ = await run(FakeModels(generate_error=error), seen=seen)

    assert result.items == [] and result.error_code == "no_llm_configured"


async def test_dropped_slots_leave_a_gap() -> None:
    rounds = 1 + RULES.practice.max_regenerations
    models = FakeModels(bad={(r, 0) for r in range(rounds)})
    seen = {item.id: NOW for item in BANK.items}

    result, _ = await run(models, seen=seen)

    assert result.error_code is None
    assert [i.position for i in result.items] == list(range(1, 6))
    assert [i.kc_id for i in result.items] == KCS[1:]


async def test_difficulty_disagreement_is_a_rejection() -> None:
    models = FakeModels()
    original = models.critique

    async def harsh(messages: Sequence[BaseMessage], schema: type[BaseModel]) -> ModelReply:
        reply = await original(messages, schema)
        data = reply.output.model_dump()
        for review in data["reviews"]:
            if review["position"] == 3 and len(models.generated) == 1:
                review["ratings"] = {k: {"level": v, "reason": "r"} for k, v in HARD.items()}
        return ModelReply(schema.model_validate(data), reply.model)

    models.critique = harsh  # type: ignore[method-assign]

    result, _ = await run(models)

    assert models.generated[1] == [3]
    assert "difficulty ratings disagree" in result.rejected[0].critic["reasons"][0]  # type: ignore[index]
