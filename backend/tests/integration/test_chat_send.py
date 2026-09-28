import ipaddress
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from app.chat.locks import ConversationLocks
from app.providers import llm, net_guard
from app.providers.config import ResolvedModel
from app.providers.net_guard import IPAddress
from app.usage import recorder as usage_recorder
from app.usage.recorder import UsageRecord

REPLY = "Great job! You could also say: I went to school."


class ProviderDown(Exception):
    pass


class StreamingFake(BaseChatModel):
    """Streams REPLY word by word with usage on the last chunk, like OpenAI does.

    fail_after: raise after this many chunks (0 = before any output).
    """

    fail_after: int | None = None

    @property
    def _llm_type(self) -> str:
        return "streaming-fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("the chat graph always streams")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        words = REPLY.split(" ")
        for i, word in enumerate(words):
            if i == self.fail_after:
                raise ProviderDown("upstream exploded")
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=word if i == 0 else f" {word}")
            )
        usage: UsageMetadata = {"input_tokens": 12, "output_tokens": 9, "total_tokens": 21}
        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=usage))


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str, port: int) -> list[IPAddress]:
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(net_guard, "resolve", fake_resolve)


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


def fake_models(monkeypatch: pytest.MonkeyPatch, **fail_after: int) -> None:
    """Replace the vendor SDK layer only: routing, context and usage callbacks stay real.

    fail_after maps a connection name to StreamingFake.fail_after.
    """

    def build(
        resolved: ResolvedModel, task: str, *, callbacks: list[Any] | None = None
    ) -> BaseChatModel:
        return StreamingFake(fail_after=fail_after.get(resolved.connection), callbacks=callbacks)

    monkeypatch.setattr(llm, "build_chat_model", build)


async def login(client: AsyncClient, email: str = "learner@example.com") -> None:
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201


async def connect(client: AsyncClient, *presets: str) -> None:
    for preset in presets:
        response = await client.post(
            "/tenant/connections", json={"preset": preset, "api_key": f"key-for-{preset}"}
        )
        assert response.status_code == 201, response.text


async def new_conversation(client: AsyncClient) -> str:
    response = await client.post("/conversations")
    assert response.status_code == 201
    conversation_id: str = response.json()["id"]
    return conversation_id


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if line and not line.startswith(":")
        )
        if fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


async def send(
    client: AsyncClient, conversation_id: str, content: str = "I goed to school yesterday."
) -> tuple[int, list[tuple[str, dict[str, Any]]], Any]:
    response = await client.post(
        f"/conversations/{conversation_id}/messages", json={"content": content}
    )
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return response.status_code, parse_sse(response.text), None
    return response.status_code, [], response.json()


async def history(client: AsyncClient, conversation_id: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = (
        await client.get(f"/conversations/{conversation_id}/messages")
    ).json()
    return data


async def test_reply_streams_as_tokens_then_done(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_models(monkeypatch)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)

    status, events, _ = await send(client, conversation_id)

    assert status == 200
    kinds = [kind for kind, _ in events]
    assert kinds[-1] == "done" and set(kinds[:-1]) == {"token"}
    assert "".join(data["text"] for kind, data in events if kind == "token") == REPLY
    done = events[-1][1]
    assert done["usage"] == {"input_tokens": 12, "output_tokens": 9}
    messages = await history(client, conversation_id)
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "I goed to school yesterday."),
        ("assistant", REPLY),
    ]
    assert done["message_id"] == messages[-1]["id"]


async def test_first_message_titles_the_conversation_and_bumps_it(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_models(monkeypatch)
    await login(client)
    await connect(client, "deepseek")
    older = await new_conversation(client)
    newer = await new_conversation(client)

    await send(client, older, "  Could you   help me practise\n job interview questions?")
    await send(client, older, "A second message must not rename it.")

    listed = (await client.get("/conversations")).json()
    assert [c["id"] for c in listed] == [older, newer]  # most recently used first
    # Whitespace collapsed, then cut to 40 characters.
    assert listed[0]["title"] == "Could you help me practise job interview"


async def test_usage_is_recorded_for_the_user_and_conversation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, usage_records: list[UsageRecord]
) -> None:
    fake_models(monkeypatch)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    me = (await client.get("/auth/me")).json()

    await send(client, conversation_id)

    [record] = usage_records
    assert record.user_id == uuid.UUID(me["user"]["id"])
    assert record.conversation_id == uuid.UUID(conversation_id)
    assert (record.task, record.connection_name, record.status) == ("chat", "deepseek", "ok")
    assert (record.input_tokens, record.output_tokens) == (12, 9)


async def test_falls_back_when_the_primary_fails_before_any_output(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, usage_records: list[UsageRecord]
) -> None:
    fake_models(monkeypatch, deepseek=0)
    await login(client)
    await connect(client, "deepseek", "openai")  # chat route: deepseek, anthropic, openai
    conversation_id = await new_conversation(client)

    _, events, _ = await send(client, conversation_id)

    assert events[-1][0] == "done"
    assert "".join(d["text"] for k, d in events if k == "token") == REPLY
    assert [(r.connection_name, r.status, r.is_fallback) for r in usage_records] == [
        ("deepseek", "error", False),
        ("openai", "ok", True),
    ]


async def test_failure_mid_reply_ends_with_an_error_event(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_models(monkeypatch, deepseek=2)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)

    status, events, _ = await send(client, conversation_id)

    assert status == 200  # headers were already sent; the failure is in the stream
    assert [k for k, _ in events] == ["token", "token", "error"]
    assert events[-1][1] == {
        "code": "llm_unavailable",
        "message": "The tutor could not reply right now. Please try again.",
    }
    assert "exploded" not in json.dumps(events)  # vendor error text is not leaked
    # The learner's message is kept; no half-written reply is.
    assert [m["role"] for m in await history(client, conversation_id)] == ["user"]
    # The lock was released, so the learner can retry straight away.
    fake_models(monkeypatch)
    llm.reset_caches()  # the failing model is cached per (tenant, task, version)
    _, retry, _ = await send(client, conversation_id, "Let me try again.")
    assert retry[-1][0] == "done"


async def test_without_a_chat_model_nothing_is_stored(client: AsyncClient) -> None:
    await login(client)
    conversation_id = await new_conversation(client)

    status, _, body = await send(client, conversation_id)

    assert status == 409
    assert body["detail"]["code"] == "no_llm_configured"
    assert await history(client, conversation_id) == []
    assert (await client.get("/conversations")).json()[0]["title"] == ""


async def test_busy_conversation_is_rejected(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_models(monkeypatch)
    await login(client)
    await connect(client, "deepseek")
    conversation_id = await new_conversation(client)
    locks: ConversationLocks = app.state.conversation_locks

    assert locks.acquire(uuid.UUID(conversation_id))  # a reply is in flight
    status, _, body = await send(client, conversation_id)
    assert status == 409 and body["detail"]["code"] == "conversation_busy"
    assert await history(client, conversation_id) == []

    locks.release(uuid.UUID(conversation_id))
    status, events, _ = await send(client, conversation_id)
    assert status == 200 and events[-1][0] == "done"
    assert locks.acquire(uuid.UUID(conversation_id))  # released again after the turn


async def test_cannot_send_to_someone_elses_conversation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_models(monkeypatch)
    await login(client, "alice@example.com")
    alice_conversation = await new_conversation(client)
    await login(client, "mallory@example.com")
    await connect(client, "deepseek")

    status, _, _ = await send(client, alice_conversation)

    assert status == 404


@pytest.mark.parametrize("content", ["", "x" * 4001])
async def test_message_length_is_validated(client: AsyncClient, content: str) -> None:
    await login(client)
    conversation_id = await new_conversation(client)

    status, _, _ = await send(client, conversation_id, content)

    assert status == 422
