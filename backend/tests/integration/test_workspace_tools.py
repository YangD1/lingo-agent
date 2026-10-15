"""The tutor's workspace tools and the open document in its prompt (ADR 0043 §5, §6)."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import SystemMessage, ToolMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkspaceDoc, WorkspaceEdit
from app.providers import llm
from app.providers.config import ResolvedModel
from app.workspace.tools import WorkspaceTools
from tests.integration.test_chat_send import parse_sse
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


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Script:
    """The fake model of test_chat_tools, answering from a script."""
    shared = Script()

    def build(resolved: ResolvedModel, task: str, *, callbacks: list[Any] | None = None) -> Any:
        return ToolFake(script=shared, callbacks=callbacks)

    monkeypatch.setattr(llm, "build_chat_model", build)
    return shared


# Long enough to open (MIN_WORDS), short enough not to be classified as writing.
ARTICLE = (
    "Scientists have found a new comet that will pass close to Earth next spring. "
    "It may be bright enough to see without a telescope, they said on Monday."
)
DRAFT = "I go to park yesterday. It was very fun and I meet my friend there."


def results(script: Script, call: int = 1) -> list[ToolMessage]:
    return [m for m in script.calls[call][1] if isinstance(m, ToolMessage)]


def system(script: Script, call: int = 0) -> str:
    return str(next(m for m in script.calls[call][1] if isinstance(m, SystemMessage)).content)


async def send_open(
    client: AsyncClient, conversation_id: str, content: str, doc_id: str | None
) -> list[tuple[str, dict[str, Any]]]:
    response = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content, "workspace_doc_id": doc_id},
    )
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


async def test_the_tutor_opens_the_learners_text(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    await send(client, conversation, ARTICLE)
    call = tool_call("open_workspace", kind="reading", source="last_message")
    script.replies = [[call], "It's open on the right."]

    status, events, _ = await send(client, conversation, "Can we read this together?")

    assert status == 200
    (card,) = kinds(events, "card")
    assert (card["kind"], card["status"]) == ("workspace", "info")
    assert card["params"]["kind"] == "reading"
    doc = (await client.get(f"/workspace/docs/{card['params']['doc_id']}")).json()
    assert (doc["created_by"], doc["source"], doc["version"]) == ("tutor", "message", 1)
    assert doc["content"]["paragraphs"] == [ARTICLE]
    (result,) = results(script, 2)
    assert result.status == "success" and "Opened the reading document" in result.text
    rows = [a for a in await activity(client, conversation) if a["name"] == "open_workspace"]
    assert rows[0]["status"] == "ok" and rows[0]["summary"]["card_kind"] == "workspace"


async def test_nothing_long_to_open_is_told_to_the_model(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    call = tool_call("open_workspace", kind="reading", source="last_message")
    script.replies = [[call], "Please paste the text first."]
    _, events, _ = await send(client, conversation, "Open my article please")
    assert kinds(events, "card") == []
    (result,) = results(script)
    assert result.status == "error" and "ask them to paste it" in result.text
    assert await db_session.scalar(select(func.count()).select_from(WorkspaceDoc)) == 0


async def test_an_article_needs_a_reading_conversation(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = [[tool_call("open_workspace", kind="reading", source="article")], "Sorry."]
    await send(client, conversation, "Open the article")
    (result,) = results(script)
    assert result.status == "error" and "no article" in result.text


async def open_draft(client: AsyncClient, conversation: str) -> str:
    response = await client.post(
        f"/conversations/{conversation}/workspace",
        json={"kind": "writing", "source": "paste", "text": DRAFT},
    )
    doc_id: str = response.json()["id"]
    return doc_id


async def test_the_open_document_is_in_the_prompt(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    doc_id = await open_draft(client, conversation)
    events = await send_open(client, conversation, "> I go to park\n\nIs this right?", doc_id)

    prompt = system(script)
    assert f"id {doc_id}, version 1" in prompt
    assert f"<workspace_doc>\n{DRAFT}\n</workspace_doc>" in prompt
    (step,) = [d for k, d in events if k == "activity" and d["name"] == "workspace_context"]
    assert step["summary"] == {"doc_id": doc_id, "version": 1, "words": 15}

    # Without it, the next turn has no document.
    await send(client, conversation, "Thanks!")
    assert "<workspace_doc>" not in system(script, 1)


async def test_a_document_of_another_conversation_is_refused(client: AsyncClient) -> None:
    conversation = await ready(client)
    other = (await client.post("/conversations")).json()["id"]
    doc_id = await open_draft(client, other)
    response = await client.post(
        f"/conversations/{conversation}/messages",
        json={"content": "Hi", "workspace_doc_id": doc_id},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "workspace_doc_not_found"


async def propose(client: AsyncClient, script: Script, conversation: str, doc_id: str) -> str:
    edits = [
        {"original": "I go to park", "replacement": "I went to the park", "reason": "Past tense."},
        {"original": "I meet", "replacement": "I met", "reason": "Past tense."},
        {"original": "not there", "replacement": "x", "reason": "Made up."},
    ]
    script.replies = [[tool_call("propose_edit", doc_id=doc_id, edits=edits)], "Have a look."]
    events = await send_open(client, conversation, "Please correct it", doc_id)
    (card,) = kinds(events, "card")
    assert card["kind"] == "workspace_edit" and card["params"]["count"] == 2
    edit_id: str = card["params"]["edit_id"]
    return edit_id


async def test_proposed_edits_wait_for_the_learner(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    doc_id = await open_draft(client, conversation)
    edit_id = await propose(client, script, conversation, doc_id)

    (result,) = results(script)
    assert result.status == "success"
    assert "Nothing has changed yet" in result.text
    assert "#3: the passage is not found" in result.text
    # Nothing changed until the learner decides.
    assert (await client.get(f"/workspace/docs/{doc_id}")).json()["version"] == 1
    (listed,) = (await client.get(f"/workspace/docs/{doc_id}/edits")).json()
    assert listed["id"] == edit_id
    assert [(i["status"], i["stale"]) for i in listed["items"]] == [("pending", False)] * 2

    decided = await client.post(
        f"/workspace/edits/{edit_id}/decide", json={"accept": [0], "decline": [1]}
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["doc"]["version"] == 2
    assert body["doc"]["content"]["text"] == DRAFT.replace("I go to park", "I went to the park")
    assert body["doc"]["versions"][-1]["author"] == "tutor"
    assert [i["status"] for i in body["edit"]["items"]] == ["accepted", "declined"]

    # Deciding again changes nothing.
    again = await client.post(f"/workspace/edits/{edit_id}/decide", json={"accept": [0, 1]})
    assert again.json()["doc"]["version"] == 2


async def test_a_passage_the_learner_changed_is_stale(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    doc_id = await open_draft(client, conversation)
    edit_id = await propose(client, script, conversation, doc_id)
    changed = DRAFT.replace("I meet", "I saw")
    await client.put(f"/workspace/docs/{doc_id}/content", json={"base_version": 1, "text": changed})

    (listed,) = (await client.get(f"/workspace/docs/{doc_id}/edits")).json()
    assert [i["stale"] for i in listed["items"]] == [False, True]
    body = (await client.post(f"/workspace/edits/{edit_id}/decide", json={"accept": [0, 1]})).json()
    assert body["doc"]["content"]["text"] == changed.replace("I go to park", "I went to the park")
    assert [i["status"] for i in body["edit"]["items"]] == ["accepted", "pending"]
    bad = await client.post(f"/workspace/edits/{edit_id}/decide", json={"accept": [5]})
    assert bad.status_code == 422


async def test_only_the_owner_decides(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    doc_id = await open_draft(client, conversation)
    edit_id = await propose(client, script, conversation, doc_id)
    await client.post("/auth/register", json={"email": "b@example.com", "password": "password123"})
    response = await client.post(f"/workspace/edits/{edit_id}/decide", json={"accept": [0]})
    assert response.status_code == 404
    assert (await client.get(f"/workspace/docs/{doc_id}/edits")).status_code == 404


async def test_edits_to_a_document_elsewhere_are_refused(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    other = (await client.post("/conversations")).json()["id"]
    doc_id = await open_draft(client, other)
    edits = [{"original": "I meet", "replacement": "I met", "reason": "Past."}]
    script.replies = [[tool_call("propose_edit", doc_id=doc_id, edits=edits)], "Hmm."]
    await send(client, conversation, "Fix my essay")
    (result,) = results(script)
    assert result.status == "error" and "no document" in result.text
    assert await db_session.scalar(select(func.count()).select_from(WorkspaceEdit)) == 0


@pytest.mark.parametrize("name", ["open_workspace", "propose_edit"])
async def test_a_call_run_twice_writes_once(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, name: str
) -> None:
    conversation = await ready(client)
    doc_id = await open_draft(client, conversation)
    owner = await db_session.get(WorkspaceDoc, uuid.UUID(doc_id))
    assert owner is not None
    tools = WorkspaceTools(
        app.state.sessionmaker,
        user_id=owner.user_id,
        tenant_id=uuid.uuid4(),
        conversation_id=owner.conversation_id,
        learner_texts=lambda: _texts(),
    )
    args: dict[str, Any] = (
        {"kind": "writing", "source": "blank"}
        if name == "open_workspace"
        else {
            "doc_id": doc_id,
            "edits": [{"original": "I meet", "replacement": "I met", "reason": "Past."}],
        }
    )
    first = await tools.run(name, args, "call-1")
    second = await tools.run(name, args, "call-1")
    assert first.draft == second.draft
    model = WorkspaceDoc if name == "open_workspace" else WorkspaceEdit
    expected = 2 if name == "open_workspace" else 1  # the draft opened above, and this one
    assert await db_session.scalar(select(func.count()).select_from(model)) == expected


async def _texts() -> list[str]:
    return []
