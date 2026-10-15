"""The tutor opens the workspace by itself, and the learner turns that off in words
(ADR 0045)."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.prompts import load_prompt
from app.providers import llm
from app.providers.config import ResolvedModel
from tests.integration.test_chat_tools import (
    Script,
    ToolFake,
    _clear_caches,  # noqa: F401
    activity,
    kinds,
    ready,
    send,
    tool_call,
)
from tests.integration.test_workspace_tools import ARTICLE, results, send_open, system


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Script:
    shared = Script()

    def build(resolved: ResolvedModel, task: str, *, callbacks: list[Any] | None = None) -> Any:
        return ToolFake(script=shared, callbacks=callbacks)

    monkeypatch.setattr(llm, "build_chat_model", build)
    return shared


async def test_the_prompt_follows_the_setting(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = ["Hi.", "Hi again."]

    await send(client, conversation, "Hello")
    first = system(script, 0)
    assert "### The workspace" in first and "{workspace_rule}" not in first
    assert load_prompt("tutor_workspace_auto") in first

    assert (await client.put("/tutor", json={"workspace_auto_open": False})).status_code == 200
    await send(client, conversation, "Hello again")
    second = system(script, 1)
    assert load_prompt("tutor_workspace_on_request") in second
    assert load_prompt("tutor_workspace_auto") not in second


async def open_doc(client: AsyncClient, conversation: str) -> str:
    response = await client.post(
        f"/conversations/{conversation}/workspace",
        json={"kind": "reading", "source": "paste", "text": ARTICLE},
    )
    assert response.status_code == 201, response.text
    doc_id: str = response.json()["id"]
    return doc_id


async def test_closing_keeps_the_document(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    doc_id = await open_doc(client, conversation)
    script.replies = [[tool_call("close_workspace")], "Closed it."]

    events = await send_open(client, conversation, "Close the panel please", doc_id)

    (card,) = kinds(events, "card")
    assert (card["kind"], card["status"]) == ("workspace_closed", "info")
    assert card["params"] == {"doc_id": doc_id, "title": card["params"]["title"]}
    (result,) = results(script)
    assert result.status == "success" and "is kept" in result.text
    assert (await client.get(f"/workspace/docs/{doc_id}")).status_code == 200
    rows = [a for a in await activity(client, conversation) if a["name"] == "close_workspace"]
    assert rows[0]["summary"]["card_kind"] == "workspace_closed"


async def test_nothing_open_to_close_is_told_to_the_model(
    client: AsyncClient, script: Script
) -> None:
    conversation = await ready(client)
    script.replies = [[tool_call("close_workspace")], "It isn't open."]
    _, events, _ = await send(client, conversation, "Close it")
    assert kinds(events, "card") == []
    (result,) = results(script)
    assert result.status == "error" and "not open" in result.text


async def test_turning_auto_open_off_in_words_and_undoing_it(
    client: AsyncClient, script: Script
) -> None:
    conversation = await ready(client)
    call = tool_call("set_workspace_auto_open", on=False)
    script.replies = [[call], "OK, I won't open it by myself."]

    _, events, _ = await send(client, conversation, "Don't open the workspace by yourself")

    (card,) = kinds(events, "card")
    assert (card["kind"], card["status"], card["params"]) == (
        "workspace_auto",
        "applied",
        {"on": False},
    )
    assert (await client.get("/tutor")).json()["workspace_auto_open"] is False
    (result,) = results(script)
    assert "only when the learner asks" in result.text
    # The next turn's prompt follows the setting.
    script.replies = ["Sure."]
    await send(client, conversation, "Thanks")
    assert load_prompt("tutor_workspace_on_request") in system(script, 2)

    undone = await client.post(f"/cards/{card['id']}/undo")
    assert undone.status_code == 200 and undone.json()["status"] == "undone"
    assert (await client.get("/tutor")).json()["workspace_auto_open"] is True


async def test_undo_refuses_after_the_setting_changed(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = [[tool_call("set_workspace_auto_open", on=False)], "OK."]
    _, events, _ = await send(client, conversation, "Stop opening it")
    (card,) = kinds(events, "card")
    assert (await client.put("/tutor", json={"workspace_auto_open": True})).status_code == 200

    response = await client.post(f"/cards/{card['id']}/undo")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "setting_changed"


async def test_the_same_setting_again_changes_nothing(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = [[tool_call("set_workspace_auto_open", on=True)], "It already is."]
    _, events, _ = await send(client, conversation, "Open it by yourself")
    (card,) = kinds(events, "card")
    assert card["status"] == "applied"
    (result,) = results(script)
    assert "already" in result.text
    assert (await client.get("/tutor")).json()["workspace_auto_open"] is True
