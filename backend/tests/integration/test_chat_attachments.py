"""Sending messages with attachments (ADR 0008 §3-4)."""

import base64
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import BaseMessage, HumanMessage
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.service import thread_config
from app.db.models import Attachment
from app.providers import llm
from app.providers.config import ResolvedModel
from tests.integration.test_attachments_api import png, settled, uploaded
from tests.integration.test_chat_send import (
    REPLY,
    StreamingFake,
    connect,
    history,
    login,
    new_conversation,
    send,
)


class RecordingFake(StreamingFake):
    """StreamingFake that remembers which connection served each call, and the input."""

    connection: str
    # Any, not list[...]: pydantic would validate a list field into a copy.
    calls: Any

    async def _astream(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.calls.append((self.connection, messages))
        async for chunk in super()._astream(messages, *args, **kwargs):
            yield chunk


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[BaseMessage]]]:
    seen: list[tuple[str, list[BaseMessage]]] = []

    def build(resolved: ResolvedModel, task: str, *, callbacks: Any = None) -> Any:
        return RecordingFake(connection=resolved.connection, calls=seen, callbacks=callbacks)

    monkeypatch.setattr(llm, "build_chat_model", build)
    return seen


async def send_with(
    client: AsyncClient, conversation_id: str, content: str, *attachment_ids: str
) -> Any:
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content, "attachment_ids": list(attachment_ids)},
    )


async def ready_image(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, conversation_id: str
) -> dict[str, Any]:
    """An uploaded image whose reading is done (the vision reader is tested elsewhere)."""
    created: dict[str, Any] = await uploaded(client, conversation_id, png(), "worksheet.png")
    await settled(client, app, created["id"])
    await db_session.execute(
        update(Attachment)
        .where(Attachment.id == uuid.UUID(created["id"]))
        .values(status="ready", error=None, text="Text in the image:\n1. I goed home.")
    )
    await db_session.commit()
    return created


async def test_documents_reach_the_model_but_not_the_checkpoint(
    client: AsyncClient, app: FastAPI, calls: list[tuple[str, list[BaseMessage]]]
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation = await new_conversation(client)
    doc = await uploaded(client, conversation, b"My essay: I goed home.", "essay.txt")
    await settled(client, app, doc["id"])

    response = await send_with(client, conversation, "Please check my essay.", doc["id"])

    assert response.status_code == 200, response.text
    ((connection, messages),) = calls
    assert connection == "deepseek"  # no image: the chat route
    assert messages[-1].text == (
        'Please check my essay.\n\n[Attachment 1: document "essay.txt"]\nMy essay: I goed home.'
    )
    # The checkpoint keeps the learner's own text; the attachment hangs off its id.
    state = await app.state.chat_graph.aget_state(thread_config(uuid.UUID(conversation)))
    stored = state.values["messages"][0]
    assert isinstance(stored, HumanMessage) and stored.content == "Please check my essay."
    turns = await history(client, conversation)
    assert [t["content"] for t in turns] == ["Please check my essay.", REPLY]
    (sent,) = turns[0]["attachments"]
    assert (sent["id"], sent["sent"], sent["filename"]) == (doc["id"], True, "essay.txt")
    assert turns[0]["id"] == stored.id
    assert turns[1]["attachments"] == []


async def test_image_turn_goes_to_the_vision_route_and_only_once(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    calls: list[tuple[str, list[BaseMessage]]],
) -> None:
    await login(client)
    await connect(client, "deepseek", "openai")  # chat: deepseek; vision: openai
    conversation = await new_conversation(client)
    image = await ready_image(client, app, db_session, conversation)
    jpeg = (await client.get(f"/attachments/{image['id']}/content")).content

    first = await send_with(client, conversation, "What did I get wrong?", image["id"])
    status, _, _ = await send(client, conversation, "Thanks! And why?")

    assert first.status_code == 200 and status == 200
    (vision_connection, vision_input), (chat_connection, chat_input) = calls
    assert (vision_connection, chat_connection) == ("openai", "deepseek")
    content = vision_input[-1].content
    assert isinstance(content, list)
    assert content[0] == {
        "type": "text",
        "text": 'What did I get wrong?\n\n[Attachment 1: image "worksheet.png"]\n'
        "Text in the image:\n1. I goed home.",
    }
    assert content[1]["type"] == "image"  # type: ignore[index]
    assert base64.b64decode(content[1]["base64"]) == jpeg  # type: ignore[index]
    # Next turn: the image is not sent again, only its reading.
    earlier = chat_input[1]
    assert isinstance(earlier.content, str)
    assert "1. I goed home." in earlier.content
    assert all(isinstance(m.content, str) for m in chat_input)


async def test_image_needs_a_vision_model_before_anything_is_sent(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    calls: list[tuple[str, list[BaseMessage]]],
) -> None:
    await login(client)
    await connect(client, "deepseek")  # chat only
    conversation = await new_conversation(client)
    image = await ready_image(client, app, db_session, conversation)

    response = await send_with(client, conversation, "Look", image["id"])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_vision_model"
    assert calls == []
    assert (await client.get(f"/attachments/{image['id']}")).json()["sent"] is False
    assert await history(client, conversation) == []


async def test_voice_message_uses_its_transcript_as_text(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    calls: list[tuple[str, list[BaseMessage]]],
) -> None:
    await login(client)
    await connect(client, "deepseek")
    conversation = await new_conversation(client)
    voice = await uploaded(client, conversation, b"OggS" + b"\x00" * 32, "voice.ogg")
    await settled(client, app, voice["id"])
    await db_session.execute(
        update(Attachment)
        .where(Attachment.id == uuid.UUID(voice["id"]))
        .values(status="ready", error=None, text="I goed home yesterday.")
    )
    await db_session.commit()

    response = await send_with(client, conversation, "", voice["id"])

    assert response.status_code == 200, response.text
    turns = await history(client, conversation)
    assert turns[0]["content"] == "I goed home yesterday."
    assert [a["kind"] for a in turns[0]["attachments"]] == ["audio"]
    conversations = (await client.get("/conversations")).json()
    assert conversations[0]["title"] == "I goed home yesterday."


async def test_image_only_message_is_titled_by_its_file(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    calls: list[tuple[str, list[BaseMessage]]],
) -> None:
    await login(client)
    await connect(client, "openai")
    conversation = await new_conversation(client)
    image = await ready_image(client, app, db_session, conversation)

    response = await send_with(client, conversation, "", image["id"])

    assert response.status_code == 200, response.text
    assert (await client.get("/conversations")).json()[0]["title"] == "worksheet.png"


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("empty", 422, "validation_error"),
        ("duplicate", 422, "invalid_attachments"),
        ("other_conversation", 404, "attachment_not_found"),
        ("unknown", 404, "attachment_not_found"),
        ("not_ready", 409, "attachment_not_ready"),
        ("already_sent", 409, "attachment_sent"),
        ("too_many_images", 422, "too_many_images"),
        ("six", 422, "validation_error"),
    ],
)
async def test_invalid_attachment_lists_are_refused(
    client: AsyncClient,
    app: FastAPI,
    db_session: AsyncSession,
    calls: list[tuple[str, list[BaseMessage]]],
    case: str,
    status: int,
    code: str,
) -> None:
    await login(client)
    await connect(client, "deepseek", "openai")
    conversation = await new_conversation(client)

    async def doc(name: str = "a.txt", target: str = conversation) -> str:
        created = await uploaded(client, target, b"text", name)
        await settled(client, app, created["id"])
        return str(created["id"])

    ids: list[str]
    if case == "empty":
        ids = []
    elif case == "duplicate":
        ids = [await doc()] * 2
    elif case == "other_conversation":
        ids = [await doc(target=await new_conversation(client))]
    elif case == "unknown":
        ids = [str(uuid.uuid4())]
    elif case == "not_ready":
        # Put it back to processing after it settles: racing the processor is flaky,
        # since a fast machine finishes a text file before the send arrives.
        ids = [await doc()]
        await db_session.execute(
            update(Attachment).where(Attachment.id == uuid.UUID(ids[0])).values(status="processing")
        )
        await db_session.commit()
    elif case == "already_sent":
        ids = [await doc()]
        assert (await send_with(client, conversation, "first", *ids)).status_code == 200
    elif case == "too_many_images":
        ids = [(await ready_image(client, app, db_session, conversation))["id"] for _ in range(5)]
    else:
        ids = [str(uuid.uuid4()) for _ in range(6)]

    response = await send_with(client, conversation, "", *ids)

    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
