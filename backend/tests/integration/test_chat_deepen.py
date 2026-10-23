"""The tutor's follow-ups end to end (ADR 0064): triggers, limits, the stream, history."""

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk

from app.agents.deepen import CONTINUE_DEEPER, OUTCOME_KEY, SEGMENT_KEY
from app.chat.service import thread_config
from app.providers import llm
from app.providers.config import ResolvedModel
from app.usage import recorder as usage_recorder
from app.usage.recorder import UsageRecord
from tests.integration.test_chat_send import connect, history, login, new_conversation, send
from tests.integration.test_chat_tools import Script, ToolFake, kinds, tool_call

DEFAULTS = {
    "enabled": True,
    "max_segments": 1,
    "first_chunk_seconds": 15,
    "total_seconds": 60,
    "max_tokens": 1500,
}


class Failing(ToolFake):
    async def _astream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        raise RuntimeError("the vendor is down")
        yield  # pragma: no cover


class Models:
    def __init__(self) -> None:
        self.tutor = Script()
        self.deep = Script()
        self.deep_fails = False


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> Models:
    shared = Models()

    def build(
        resolved: ResolvedModel, task: str, *, callbacks: list[Any] | None = None
    ) -> BaseChatModel:
        if task == "chat_deep":
            fake = Failing if shared.deep_fails else ToolFake
            return fake(script=shared.deep, callbacks=callbacks)
        return ToolFake(script=shared.tutor, callbacks=callbacks)

    monkeypatch.setattr(llm, "build_chat_model", build)
    return shared


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    llm.reset_caches()
    yield
    llm.reset_caches()


@pytest.fixture
def usage_records() -> Iterator[list[UsageRecord]]:
    records: list[UsageRecord] = []
    usage_recorder.set_usage_sink(records.append)
    yield records
    usage_recorder.set_usage_sink(None)


async def ready(client: AsyncClient, **limits: Any) -> str:
    await login(client)
    await connect(client, "openai")
    if limits:
        put = await client.put("/tenant/deepen", json={**DEFAULTS, **limits})
        assert put.status_code == 200
    return await new_conversation(client)


async def activity(client: AsyncClient, conversation: str) -> list[dict[str, Any]]:
    data = (await client.get(f"/conversations/{conversation}/activity")).json()
    return [a for a in data["activities"] if a["name"] == "deepen"]


async def test_a_why_question_gets_a_follow_up_under_the_reply(
    client: AsyncClient, app: FastAPI, models: Models, usage_records: list[UsageRecord]
) -> None:
    conversation = await ready(client)
    models.tutor.replies = ["It's the present perfect."]
    models.deep.replies = ["It links a past action to now."]

    status, events, _ = await send(client, conversation, "Why is it 'has gone' here?")

    assert status == 200
    order = [(k, d.get("text") or d.get("state")) for k, d in events if k in ("token", "segment")]
    assert order == [
        ("token", "It's the present perfect."),
        ("segment", "started"),
        ("token", "\n\n"),  # older clients show the parts joined, like history
        ("token", "It links a past action to now."),
        ("segment", "ended"),
    ]
    (ended,) = [d for d in kinds(events, "segment") if d["state"] == "ended"]
    assert (ended["index"], ended["outcome"]) == (1, "done")

    # The follow-up model got no tools, the reply as its last answer and the cue last.
    (offered, deep_input) = models.deep.calls[0]
    assert offered is None
    assert isinstance(deep_input[0], SystemMessage)
    assert "Writing the follow-up" in deep_input[0].text
    assert (
        isinstance(deep_input[-2], AIMessage) and deep_input[-2].text == "It's the present perfect."
    )
    assert isinstance(deep_input[-1], HumanMessage) and "Write the follow-up" in deep_input[-1].text
    # The tutor was told one is coming, and wasn't offered the tool.
    (tutor_offered, tutor_input) = models.tutor.calls[0]
    assert "A deeper follow-up will be written under your reply" in tutor_input[0].text
    assert CONTINUE_DEEPER not in (tutor_offered or [])

    turns = await history(client, conversation)
    assert turns[-1]["content"] == "It's the present perfect.\n\nIt links a past action to now."
    (done,) = kinds(events, "done")
    assert done["message_id"] == turns[-1]["id"]
    state = await app.state.chat_graph.aget_state(thread_config(uuid.UUID(conversation)))
    last = state.values["messages"][-1]
    assert (last.additional_kwargs[SEGMENT_KEY], last.additional_kwargs[OUTCOME_KEY]) == (1, "done")

    (step,) = await activity(client, conversation)
    assert (step["status"], step["call_id"]) == ("ok", "1")
    assert step["summary"] == {"segment": 1, "trigger": "rule", "outcome": "done", "reason": None}
    assert [r.task for r in usage_records] == ["chat", "chat_deep"]


async def test_the_tutor_asks_for_one(client: AsyncClient, models: Models) -> None:
    conversation = await ready(client)
    ask = tool_call(CONTINUE_DEEPER, reason="how it differs from the past simple")
    models.tutor.replies = [("Use it for past actions that matter now.", [ask])]
    models.deep.replies = ["Compare: I lost my key / I have lost my key."]

    status, events, _ = await send(client, conversation, "Explain the present perfect please")

    assert status == 200
    # One tutor call: asking for a follow-up needs no second one (ADR 0057).
    ((offered, _),) = models.tutor.calls
    assert offered is not None and offered[-1] == CONTINUE_DEEPER
    assert len(models.deep.calls) == 1
    text = "".join(e["text"] for e in kinds(events, "token"))
    assert text.endswith("I have lost my key.")
    # The deep model's history keeps the reply's text, not the call and its result.
    (_, deep_input) = models.deep.calls[0]
    assert not any(isinstance(m, ToolMessage) for m in deep_input)

    (step,) = await activity(client, conversation)
    assert step["summary"]["trigger"] == "model"
    assert step["summary"]["reason"] == "how it differs from the past simple"


async def test_small_talk_and_a_tenant_that_turned_them_off_get_none(
    client: AsyncClient, models: Models
) -> None:
    conversation = await ready(client)
    status, events, _ = await send(client, conversation, "Hi there")
    assert status == 200 and models.deep.calls == []
    assert kinds(events, "segment") == []

    put = await client.put("/tenant/deepen", json={**DEFAULTS, "enabled": False})
    assert put.status_code == 200
    status, _, _ = await send(client, conversation, "Why is it 'has gone'?")
    assert status == 200 and models.deep.calls == []
    (offered, prompt) = models.tutor.calls[-1]
    assert CONTINUE_DEEPER not in (offered or [])
    assert "### Follow-ups" not in prompt[0].text


async def test_more_follow_ups_up_to_the_tenants_limit(client: AsyncClient, models: Models) -> None:
    conversation = await ready(client, max_segments=2)
    models.tutor.replies = ["Short."]
    more = tool_call(CONTINUE_DEEPER, reason="the second question")
    models.deep.replies = [
        ("Part one.", [more]),
        ("Part two.", [tool_call(CONTINUE_DEEPER, reason="x")]),
    ]

    status, events, _ = await send(client, conversation, "Why A, and what about B?")

    assert status == 200
    (first_offered, _), (second_offered, _) = models.deep.calls
    assert first_offered == [CONTINUE_DEEPER]
    assert second_offered is None  # the last one allowed can't ask for more
    assert [d["index"] for d in kinds(events, "segment") if d["state"] == "ended"] == [1, 2]
    turns = await history(client, conversation)
    assert turns[-1]["content"] == "Short.\n\nPart one.\n\nPart two."

    # The next turn's history has a result for the follow-up's call.
    models.tutor.replies = ["Sure."]
    status, _, _ = await send(client, conversation, "ok")
    (_, next_input) = models.tutor.calls[-1]
    results = [m for m in next_input if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in results] == [more["id"]]


async def test_a_failed_follow_up_leaves_the_reply(client: AsyncClient, models: Models) -> None:
    conversation = await ready(client)
    models.tutor.replies = ["It's the present perfect."]
    models.deep_fails = True

    status, events, _ = await send(client, conversation, "Why is it 'has gone'?")

    assert status == 200
    assert kinds(events, "error") == []
    assert len(kinds(events, "done")) == 1
    (ended,) = [d for d in kinds(events, "segment") if d["state"] == "ended"]
    assert ended["outcome"] == "failed"
    turns = await history(client, conversation)
    assert turns[-1]["content"] == "It's the present perfect."
    (step,) = await activity(client, conversation)
    assert (step["status"], step["summary"]) == ("failed", {})
