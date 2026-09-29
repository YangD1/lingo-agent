"""Placement graph on a real Postgres checkpointer: interrupt, resume, pick up later."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.adaptive.placement.flow import PlacementResult
from app.adaptive.placement.items import get_item_bank
from app.adaptive.placement.words import WordPool
from app.adaptive.rules import get_rules
from app.agents.placement_graph import (
    PlacementContext,
    PlacementGraph,
    build_placement_graph,
    start_state,
)
from app.db.urls import to_psycopg_conninfo
from tests.conftest import TEST_DATABASE_URL
from tests.unit.placement_fixtures import POOL

BANK = get_item_bank()


@pytest.fixture
async def checkpointer(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> AsyncIterator[AsyncPostgresSaver]:
    # db_session: its teardown truncates the checkpoint tables after each test.
    async with AsyncPostgresSaver.from_conn_string(to_psycopg_conninfo(TEST_DATABASE_URL)) as saver:
        yield saver


class Words:
    async def pool(self) -> WordPool:
        return POOL


class Saved:
    def __init__(self) -> None:
        self.results: list[PlacementResult] = []

    async def __call__(self, result: PlacementResult) -> None:
        self.results.append(result)


def context(saved: Saved) -> PlacementContext:
    return PlacementContext(words=Words(), bank=BANK, rules=get_rules(), save=saved)


def config() -> RunnableConfig:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def asked(out: dict[str, Any]) -> dict[str, Any] | None:
    """The question the graph stopped at, as the learner sees it."""
    interrupts = out.get("__interrupt__") or ()
    return interrupts[0].value if interrupts else None


def reply(question: dict[str, Any]) -> dict[str, Any]:
    if question["stage"] == "vocab":
        return {"question_id": question["id"], "yes": question["index"] % 2 == 0}
    return {"question_id": question["id"], "choice": question["index"] % 4}


async def test_resumes_at_the_same_question_in_a_new_graph(
    checkpointer: AsyncPostgresSaver,
) -> None:
    saved = Saved()
    cfg = config()
    graph = build_placement_graph(checkpointer)
    question = asked(await graph.ainvoke(start_state(seed=11), cfg, context=context(saved)))
    assert question is not None and question["id"] == "vocab-0"
    assert "rank" not in question and "word_id" not in question
    for _ in range(3):
        out = await graph.ainvoke(Command(resume=reply(question)), cfg, context=context(saved))
        question = asked(out)
        assert question is not None
    assert question["id"] == "vocab-3"

    # A fresh process: a new graph and saver on the same database.
    async with AsyncPostgresSaver.from_conn_string(to_psycopg_conninfo(TEST_DATABASE_URL)) as saver:
        later: PlacementGraph = build_placement_graph(saver)
        state = await later.aget_state(cfg)
        assert state.interrupts[0].value == question
        out = await later.ainvoke(Command(resume=reply(question)), cfg, context=context(saved))
        after = asked(out)
    assert after is not None and after["id"] == "vocab-4"
    assert len(out["progress"]["vocab"]) == 4


async def test_an_answer_for_another_question_is_dropped(
    checkpointer: AsyncPostgresSaver,
) -> None:
    saved = Saved()
    cfg = config()
    graph = build_placement_graph(checkpointer)
    question = asked(await graph.ainvoke(start_state(seed=12), cfg, context=context(saved)))
    assert question is not None
    out = await graph.ainvoke(
        Command(resume={"question_id": "vocab-5", "yes": True}), cfg, context=context(saved)
    )
    assert asked(out) == question
    assert out["progress"]["vocab"] == []


async def test_a_whole_test_saves_one_result(checkpointer: AsyncPostgresSaver) -> None:
    saved = Saved()
    cfg = config()
    graph = build_placement_graph(checkpointer)
    out = await graph.ainvoke(start_state(seed=13), cfg, context=context(saved))
    stages = []
    while (question := asked(out)) is not None:
        stages.append(question["stage"])
        out = await graph.ainvoke(Command(resume=reply(question)), cfg, context=context(saved))
    assert stages[0] == "vocab" and stages[-1] == "grammar"
    assert len(saved.results) == 1
    assert out["result"] == saved.results[0]
    assert out["result"]["cefr"] in ("A1", "A2", "B1", "B2", "C1", "C2")
    assert (await graph.aget_state(cfg)).next == ()
