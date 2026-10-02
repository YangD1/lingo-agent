"""Which coach answers a conversation (ADR 0023 §3, tasks 37.1 and 38.4)."""

import asyncio
import uuid
from typing import Any

import pytest
from langchain_core.runnables import RunnableLambda

from app.agents import routing
from app.agents.routing import Route, RouteDecision, classify, route_for, worth_classifying
from app.api.chat import Turn
from app.providers import llm
from tests.unit.provider_fixtures import make_ctx


def test_practice_conversations_go_to_grammar_coach() -> None:
    assert route_for("g.past_simple_irregular") is Route.GRAMMAR_COACH


def test_free_planning_and_daily_conversations_stay_with_the_tutor() -> None:
    # Planning and daily conversations have no grammar point: the tutor answers them,
    # with their brief and limited tools.
    assert route_for(None) is Route.TUTOR


def test_only_long_messages_are_worth_classifying() -> None:
    # Q38a: English words in the typed text; Chinese and numbers don't count.
    assert not worth_classifying(" ".join(["word"] * 59) + " 这是中文 123")
    assert worth_classifying(" ".join(["word"] * 60))


def _serve(monkeypatch: pytest.MonkeyPatch, answer: Any) -> list[Any]:
    seen: list[Any] = []

    async def respond(messages: Any) -> RouteDecision:
        seen.append(messages)
        if isinstance(answer, BaseException):
            raise answer
        if answer is None:
            return None  # type: ignore[return-value]
        if answer == "slow":
            await asyncio.sleep(1)
        return RouteDecision(route=answer if answer != "slow" else "writing_coach")

    monkeypatch.setattr(
        routing, "get_structured_llm", lambda ctx, task, schema: RunnableLambda(respond)
    )
    return seen


async def test_classify_follows_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _serve(monkeypatch, "writing_coach")

    route = await classify(make_ctx(), "My essay ...", "Write about your summer.", {})

    assert route is Route.WRITING_COACH
    [[_system, prompt]] = seen
    assert "Write about your summer." in prompt.content
    assert "My essay ..." in prompt.content


async def test_a_failed_call_stays_with_the_tutor(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, RuntimeError("provider down"))

    assert await classify(make_ctx(), "text", "", {}) is Route.TUTOR


async def test_a_reply_without_the_tool_call_stays_with_the_tutor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A model that answers in text instead of calling the tool parses to None.
    _serve(monkeypatch, None)

    assert await classify(make_ctx(), "text", "", {}) is Route.TUTOR


async def test_no_model_configured_stays_with_the_tutor() -> None:
    llm.reset_caches()
    # A tenant without connections: building the model raises NoModelConfiguredError.
    assert await classify(make_ctx(), "text", "", {}) is Route.TUTOR


async def test_slow_classification_stays_with_the_tutor(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, "slow")
    monkeypatch.setattr(routing, "TIMEOUT_SECONDS", 0.01)

    assert await classify(make_ctx(), "text", "", {}) is Route.TUTOR


@pytest.mark.parametrize(
    ("focus", "planning", "text", "free"),
    [
        (None, None, "Hi", True),
        (None, None, None, False),  # an opening
        (None, "daily", "Hi", False),
        ("g.past_simple_irregular", None, "Hi", False),
    ],
)
def test_only_learner_messages_in_free_chat_are_classified(
    focus: str | None, planning: Any, text: str | None, free: bool
) -> None:
    turn = Turn(uuid.uuid4(), make_ctx(), text, "m1", focus, planning)
    assert turn.free_chat is free
