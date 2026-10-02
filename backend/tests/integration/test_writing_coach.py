"""writing_coach in free chat (task 38.5): the learner's text is reviewed with the
`/writing` service, a card links to the review, and the coach comments on it."""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import chat_graph
from app.agents.routing import Route
from app.db.models import KCEvidence, WritingSubmission
from app.providers.config import TenantProviderContext
from tests.integration.test_chat_send import send
from tests.integration.test_chat_tools import (
    Script,
    _clear_caches,  # noqa: F401
    activity,
    cards,
    kinds,
    ready,
    script,  # noqa: F401
    system_text,
    tool_call,
)
from tests.integration.test_writing_api import fake_worker
from tests.integration.test_writing_service import TEXT, FakeReview

# The reviewed TEXT (26 words, three mistakes) and enough more to be classified.
ESSAY = (
    TEXT + "\n\nAfter lunch we sat on a bench near the water and watched the boats. "
    "My friend told me about her new job in the city and her plans for the summer. "
    "In the evening we went home by bus because we were very tired."
)


@pytest.fixture(autouse=True)
def to_writing_coach(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The classifier hands every message it is asked about to writing_coach."""
    asked: list[str] = []

    async def classify(
        ctx: TenantProviderContext, text: str, previous: str, config: RunnableConfig
    ) -> Route:
        asked.append(text)
        return Route.WRITING_COACH

    monkeypatch.setattr(chat_graph, "classify", classify)
    return asked


def step(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    (row,) = [r for r in rows if r["name"] == name]
    return row


async def test_after_a_tool_call_the_next_turn_is_reviewed_by_writing_coach(
    client: AsyncClient,
    app: FastAPI,
    script: Script,  # noqa: F811
    db_session: AsyncSession,
) -> None:
    conversation = await ready(client)
    fake_worker(app, FakeReview())
    script.replies = [
        [tool_call("suggest_link", kind="learner")],
        "Here is your learner model.",
        "Nice story! Watch your past tense.",
    ]

    # A short message stays with the tutor, which leaves a tool call in the history.
    await send(client, conversation, "Show me my weak points")
    status, events, _ = await send(client, conversation, ESSAY)

    assert status == 200
    # The coach was offered no tools and sent no tool messages or tool calls, which
    # some vendors refuse without tool definitions; the tutor's text is kept.
    offered, messages = script.calls[-1]
    assert offered is None
    assert not any(isinstance(m, ToolMessage) for m in messages)
    assert not any(isinstance(m, AIMessage) and m.tool_calls for m in messages)
    assert any(m.text == "Here is your learner model." for m in messages)
    # It was told the review: the summary and the corrections.
    prompt = system_text(messages)
    assert "Good start." in prompt and '"walk" -> "fixed"' in prompt

    # The card links to the submission, kept with this conversation.
    (card,) = kinds(events, "card")
    submission = await db_session.scalar(select(WritingSubmission))
    assert submission is not None
    assert (card["kind"], card["status"]) == ("writing", "info")
    assert card["params"] == {"submission_id": submission.id}
    assert str(submission.conversation_id) == conversation
    assert submission.status == "done" and submission.text == ESSAY
    evidence = await db_session.scalar(
        select(func.count()).where(KCEvidence.writing_id == submission.id)
    )
    assert evidence == 3
    assert [c["kind"] for c in await cards(client, conversation)] == ["link", "writing"]

    rows = await activity(client, conversation)
    assert step(rows, "handoff")["summary"] == {"coach": "writing_coach"}
    review = step(rows, "writing_review")
    assert review["status"] == "ok"
    assert review["summary"] == {"submission_id": submission.id, "mistakes": 3}
    text = "".join(e["text"] for e in kinds(events, "token"))
    assert text == "Nice story! Watch your past tense."


async def test_a_failed_review_still_gets_a_reply(
    client: AsyncClient,
    app: FastAPI,
    script: Script,  # noqa: F811
) -> None:
    conversation = await ready(client)
    fake_worker(app, FakeReview(error=RuntimeError("provider down")))
    script.replies = ["Good effort! A few notes on tenses."]

    status, events, _ = await send(client, conversation, ESSAY)

    assert status == 200
    assert "".join(e["text"] for e in kinds(events, "token")) == (
        "Good effort! A few notes on tenses."
    )
    _, messages = script.calls[-1]
    assert "could not be done this time" in system_text(messages)
    review = step(await activity(client, conversation), "writing_review")
    assert review["status"] == "failed"
    # The card still leads to the submission, which says it failed.
    (card,) = kinds(events, "card")
    assert card["kind"] == "writing"


async def test_short_messages_are_not_classified(
    client: AsyncClient,
    script: Script,  # noqa: F811
    to_writing_coach: list[str],
) -> None:
    conversation = await ready(client)

    await send(client, conversation, "Hi, how are you?")

    assert to_writing_coach == []
