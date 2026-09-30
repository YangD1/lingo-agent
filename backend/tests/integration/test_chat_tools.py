"""The tutor's tool calls end to end (ADR 0015): cards, the tool loop, fallbacks."""

import json
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import AsyncClient
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessageChunk, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chat_graph import MAX_CALLS_PER_ROUND, MAX_TOOL_ROUNDS
from app.db.models import UserWordBook
from app.providers import llm
from app.providers.config import ResolvedModel
from app.usage import recorder as usage_recorder
from app.usage.recorder import UsageRecord
from tests.integration.test_chat_send import connect, history, login, new_conversation, send

KC = "g.word_order_svo"


def tool_call(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}


@dataclass
class Script:
    """What the fake model answers, call by call: a text, or a list of tool calls."""

    replies: list[str | list[dict[str, Any]]] = field(default_factory=list)
    # Each call: the tools it was offered (None = none bound) and the messages it got.
    calls: list[tuple[list[str] | None, list[BaseMessage]]] = field(default_factory=list)
    refuse_tools: bool = False


class VendorRefused(Exception):
    status_code = 400


class ToolFake(BaseChatModel):
    script: Any

    @property
    def _llm_type(self) -> str:
        return "tool-fake"

    def bind_tools(
        self, tools: Sequence[Any], **kwargs: Any
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], **kwargs)

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
        script: Script = self.script
        tools = kwargs.get("tools")
        if tools and script.refuse_tools:
            raise VendorRefused("tools are not supported")
        script.calls.append(
            ([t["function"]["name"] for t in tools] if tools else None, list(messages))
        )
        reply = script.replies.pop(0) if script.replies else "All set."
        usage = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
        if isinstance(reply, str):
            yield ChatGenerationChunk(message=AIMessageChunk(content=reply, usage_metadata=usage))  # type: ignore[arg-type]
            return
        chunks = [
            {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
            for i, c in enumerate(reply)
        ]
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", tool_call_chunks=chunks, usage_metadata=usage)  # type: ignore[arg-type]
        )


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Script:
    shared = Script()

    def build(
        resolved: ResolvedModel, task: str, *, callbacks: list[Any] | None = None
    ) -> BaseChatModel:
        return ToolFake(script=shared, callbacks=callbacks)

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


async def ready(client: AsyncClient) -> str:
    await login(client)
    await connect(client, "openai")
    return await new_conversation(client)


def kinds(events: list[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [data for k, data in events if k == kind]


async def activity(client: AsyncClient, conversation_id: str) -> list[dict[str, Any]]:
    body = (await client.get(f"/conversations/{conversation_id}/activity")).json()
    return list(body["activities"])


async def cards(client: AsyncClient, conversation_id: str) -> list[dict[str, Any]]:
    return list((await client.get(f"/conversations/{conversation_id}/cards")).json()["cards"])


def system_text(messages: list[BaseMessage]) -> str:
    return next(m.text for m in messages if isinstance(m, SystemMessage))


# --- the tool loop ------------------------------------------------------------------------


async def test_a_proposal_shows_a_card_and_the_reply_goes_on(
    client: AsyncClient, script: Script, usage_records: list[UsageRecord]
) -> None:
    conversation = await ready(client)
    call = tool_call("propose_word_book", book_id="cet4", daily_new=15)
    script.replies = [[call], "I've suggested CET-4 with 15 new words a day."]

    status, events, _ = await send(client, conversation, "Can you set me up for CET-4?")

    assert status == 200
    (card,) = kinds(events, "card")
    assert (card["kind"], card["status"], card["params"]) == (
        "word_book",
        "proposed",
        {"book_id": "cet4", "daily_new": 15},
    )
    assert card["display"]["book"]["id"] == "cet4"
    text = "".join(e["text"] for e in kinds(events, "token"))
    assert text == "I've suggested CET-4 with 15 new words a day."

    # Offered the tools, then told what happened; nothing was changed yet.
    (offered, _), (_, followup) = script.calls
    assert offered == [
        "propose_word_book",
        "propose_learning_goal",
        "suggest_practice",
        "suggest_link",
    ]
    (result,) = [m for m in followup if isinstance(m, ToolMessage)]
    assert result.tool_call_id == call["id"] and result.status == "success"
    assert "until the learner confirms" in result.text
    assert (await client.get("/vocab")).json()["book_id"] is None

    # One tutor message in history, under the id `done` gave.
    (done,) = kinds(events, "done")
    messages = await history(client, conversation)
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "Can you set me up for CET-4?"),
        ("assistant", "I've suggested CET-4 with 15 new words a day."),
    ]
    assert done["message_id"] == messages[-1]["id"]

    # The follow-up call isn't a new learner turn.
    assert [r.task for r in usage_records] == ["chat", "chat_tools"]
    assert usage_records[1].user_id is not None
    assert str(usage_records[1].conversation_id) == conversation

    (tool_row,) = [a for a in await activity(client, conversation) if a["kind"] == "tool"]
    assert (tool_row["name"], tool_row["status"], tool_row["call_id"]) == (
        "propose_word_book",
        "ok",
        call["id"],
    )
    assert tool_row["summary"] == {"card_id": card["id"], "card_kind": "word_book"}
    (listed,) = await cards(client, conversation)
    assert listed["id"] == card["id"] and listed["turn_id"] == done["turn_id"]


async def test_the_next_turn_knows_what_became_of_a_card(
    client: AsyncClient, script: Script
) -> None:
    conversation = await ready(client)
    script.replies = [[tool_call("propose_word_book", book_id="ielts")], "Suggested."]
    _, events, _ = await send(client, conversation, "IELTS please")
    (card,) = kinds(events, "card")
    assert (await client.post(f"/cards/{card['id']}/apply")).status_code == 200

    script.replies = ["Great, you're on IELTS now."]
    await send(client, conversation, "Done!")

    prompt = system_text(script.calls[-1][1])
    assert "switch the word book to IELTS" in prompt
    assert "the learner confirmed it" in prompt
    # History keeps the tool exchange for the model.
    assert any(isinstance(m, ToolMessage) for m in script.calls[-1][1])


async def test_a_refused_call_goes_back_to_the_model_without_a_card(
    client: AsyncClient, script: Script
) -> None:
    conversation = await ready(client)
    script.replies = [[tool_call("propose_word_book", book_id="klingon")], "Sorry, try again."]

    _, events, _ = await send(client, conversation, "Klingon words please")

    assert kinds(events, "card") == []
    (result,) = [m for m in script.calls[1][1] if isinstance(m, ToolMessage)]
    assert result.status == "error" and "unknown book_id 'klingon'" in result.text
    (row,) = [a for a in await activity(client, conversation) if a["kind"] == "tool"]
    assert (row["status"], row["summary"]) == ("failed", {})
    assert await cards(client, conversation) == []


async def test_tool_rounds_and_calls_are_capped(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    many = [tool_call("suggest_link", kind="vocab_review") for _ in range(MAX_CALLS_PER_ROUND + 1)]
    script.replies = [many, [tool_call("suggest_link", kind="placement")], "Here you go."]

    _, events, _ = await send(client, conversation, "What should I do?")

    assert len(script.calls) == MAX_TOOL_ROUNDS + 1
    # The last call has no tools and is told it can't use them.
    assert [offered is not None for offered, _ in script.calls] == [True, True, False]
    assert "can't change the learner's settings" in system_text(script.calls[-1][1])
    results = [m for m in script.calls[1][1] if isinstance(m, ToolMessage)]
    assert [r.status for r in results] == ["success"] * MAX_CALLS_PER_ROUND + ["error"]
    # The same shortcut twice in one turn is one card.
    assert [c["params"]["kind"] for c in kinds(events, "card")] == ["vocab_review"] * 3 + [
        "placement"
    ]
    assert [c["params"]["kind"] for c in await cards(client, conversation)] == [
        "vocab_review",
        "placement",
    ]


async def test_a_vendor_refusing_tools_gets_the_turn_without_them(
    client: AsyncClient, script: Script
) -> None:
    conversation = await ready(client)
    script.refuse_tools = True
    script.replies = ["You can pick a book on [the books page](/vocab/books)."]

    status, events, _ = await send(client, conversation, "Change my book")

    assert status == 200
    assert "".join(e["text"] for e in kinds(events, "token")).startswith("You can pick")
    ((offered, messages),) = script.calls
    assert offered is None
    assert "/vocab/books" in system_text(messages)
    skipped = [a for a in kinds(events, "activity") if a["name"] == "tools"]
    assert [(a["kind"], a["status"]) for a in skipped] == [("step", "skipped")]


async def test_practice_conversations_have_no_tools(client: AsyncClient, script: Script) -> None:
    await login(client)
    await connect(client, "openai")
    created = await client.post("/conversations", json={"focus_kc_id": KC})
    conversation = created.json()["id"]

    await send(client, conversation, "I like apples.")

    ((offered, messages),) = script.calls
    assert offered is None
    assert "Arranging the learner's study" not in system_text(messages)


# --- applying, declining, undoing ---------------------------------------------------------


async def proposal(client: AsyncClient, script: Script, name: str, **args: Any) -> dict[str, Any]:
    conversation = await ready(client)
    script.replies = [[tool_call(name, **args)], "Suggested."]
    _, events, _ = await send(client, conversation)
    (card,) = kinds(events, "card")
    return card


async def test_a_word_book_is_applied_and_undone_back_to_no_book(
    client: AsyncClient, script: Script
) -> None:
    card = await proposal(client, script, "propose_word_book", book_id="cet4", daily_new=15)

    applied = await client.post(f"/cards/{card['id']}/apply")
    assert applied.status_code == 200 and applied.json()["status"] == "applied"
    vocab = (await client.get("/vocab")).json()
    assert (vocab["book_id"], vocab["daily_new"]) == ("cet4", 15)
    # Applying twice changes nothing.
    assert (await client.post(f"/cards/{card['id']}/apply")).json()["status"] == "applied"

    undone = await client.post(f"/cards/{card['id']}/undo")
    assert undone.status_code == 200 and undone.json()["status"] == "undone"
    assert (await client.get("/vocab")).json()["book_id"] is None
    assert (await client.post(f"/cards/{card['id']}/apply")).status_code == 409


async def test_undo_restores_the_old_book_and_screening_position(
    client: AsyncClient, script: Script, db_session: AsyncSession
) -> None:
    card = await proposal(client, script, "propose_word_book", book_id="ielts")
    put = await client.put("/vocab/book", json={"book_id": "cet4", "daily_new": 20})
    assert put.status_code == 204
    await db_session.execute(update(UserWordBook).values(screen_offset=300))
    await db_session.commit()

    await client.post(f"/cards/{card['id']}/apply")
    vocab = (await client.get("/vocab")).json()
    assert (vocab["book_id"], vocab["daily_new"]) == ("ielts", 20)  # daily_new kept

    assert (await client.post(f"/cards/{card['id']}/undo")).status_code == 200
    vocab = (await client.get("/vocab")).json()
    assert (vocab["book_id"], vocab["daily_new"]) == ("cet4", 20)
    offset = await db_session.scalar(select(UserWordBook.screen_offset))
    assert offset == 300


async def test_undo_refuses_when_the_setting_changed_since(
    client: AsyncClient, script: Script
) -> None:
    card = await proposal(client, script, "propose_word_book", book_id="ielts")
    await client.post(f"/cards/{card['id']}/apply")
    await client.put("/vocab/book", json={"book_id": "gre", "daily_new": None})

    response = await client.post(f"/cards/{card['id']}/undo")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "setting_changed"
    assert (await client.get("/vocab")).json()["book_id"] == "gre"


async def test_a_goal_is_applied_as_the_learners_own_and_undone(
    client: AsyncClient, script: Script
) -> None:
    await login(client)
    await client.patch("/profile", json={"goal": "travel"})
    before = (await client.get("/profile")).json()
    conversation = await new_conversation(client)
    await connect(client, "openai")
    script.replies = [
        [tool_call("propose_learning_goal", target_exam="ielts", daily_minutes=30)],
        "Suggested.",
    ]
    _, events, _ = await send(client, conversation)
    (card,) = kinds(events, "card")
    assert card["params"] == {"target_exam": "ielts", "daily_minutes": 30}

    await client.post(f"/cards/{card['id']}/apply")
    profile = (await client.get("/profile")).json()
    assert (profile["goal"], profile["target_exam"], profile["daily_minutes"]) == (
        "travel",
        "ielts",
        30,
    )
    assert {"target_exam", "daily_minutes"} <= set(profile["manual_fields"])

    await client.post(f"/cards/{card['id']}/undo")
    profile = (await client.get("/profile")).json()
    assert (profile["target_exam"], profile["daily_minutes"]) == (None, None)
    assert profile["manual_fields"] == before["manual_fields"]


async def test_decline_and_ownership(client: AsyncClient, script: Script) -> None:
    card = await proposal(client, script, "propose_word_book", book_id="cet6")

    declined = await client.post(f"/cards/{card['id']}/decline")
    assert declined.json()["status"] == "declined"
    assert (await client.post(f"/cards/{card['id']}/apply")).status_code == 409
    assert (await client.post(f"/cards/{card['id']}/undo")).status_code == 409

    await login(client, "someone-else@example.com")
    response = await client.post(f"/cards/{card['id']}/decline")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "card_not_found"
    assert (await client.post(f"/cards/{uuid.uuid4()}/apply")).status_code == 404


async def test_link_cards_carry_live_numbers(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = [
        [tool_call("suggest_link", kind="placement"), tool_call("suggest_practice", kc_id=KC)],
        "Two ideas.",
    ]
    await send(client, conversation)

    link, practice = await cards(client, conversation)

    assert (link["status"], link["live"]) == ("info", {"days_since": None, "in_progress": False})
    assert practice["live"] is None
    assert practice["display"]["kc"]["id"] == KC
