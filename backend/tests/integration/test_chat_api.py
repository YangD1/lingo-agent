import uuid
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.chat_graph import ChatGraph
from app.chat.service import thread_config


async def login(client: AsyncClient, email: str = "learner@example.com") -> None:
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201


async def new_conversation(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/conversations")
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def graph_of(app: FastAPI) -> ChatGraph:
    graph: ChatGraph = app.state.chat_graph
    return graph


async def seed_history(app: FastAPI, conversation_id: str) -> None:
    await graph_of(app).aupdate_state(
        thread_config(uuid.UUID(conversation_id)),
        {
            "messages": [
                HumanMessage("I goed to school.", id="m1"),
                AIMessage(
                    [{"type": "text", "text": "Nice! "}, {"type": "text", "text": "Say *went*."}],
                    id="m2",
                ),
                SystemMessage("internal note", id="m3"),
            ]
        },
    )


async def test_endpoints_require_login(client: AsyncClient) -> None:
    some_id = uuid.uuid4()
    assert (await client.get("/conversations")).status_code == 401
    assert (await client.post("/conversations")).status_code == 401
    assert (await client.get(f"/conversations/{some_id}/messages")).status_code == 401
    assert (await client.delete(f"/conversations/{some_id}")).status_code == 401


async def test_create_and_list_newest_first(client: AsyncClient) -> None:
    await login(client)
    first = await new_conversation(client)
    second = await new_conversation(client)

    assert first["title"] == ""
    listed = (await client.get("/conversations")).json()
    # Same-transaction timestamps can tie; ordering must still be deterministic.
    assert {c["id"] for c in listed} == {first["id"], second["id"]}
    assert listed == sorted(listed, key=lambda c: c["updated_at"], reverse=True)


async def test_new_conversation_has_no_messages(client: AsyncClient) -> None:
    await login(client)
    conversation = await new_conversation(client)

    response = await client.get(f"/conversations/{conversation['id']}/messages")

    assert response.status_code == 200
    assert response.json() == []


async def test_history_is_read_back_from_the_checkpoint(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)
    await seed_history(app, conversation["id"])

    response = await client.get(f"/conversations/{conversation['id']}/messages")

    assert response.json() == [
        {"id": "m1", "role": "user", "content": "I goed to school.", "attachments": []},
        # Content blocks (e.g. from Anthropic) are flattened to plain text.
        {"id": "m2", "role": "assistant", "content": "Nice! Say *went*.", "attachments": []},
        # System messages are internal and never returned.
    ]


async def test_other_users_conversations_are_invisible(client: AsyncClient, app: FastAPI) -> None:
    await login(client, "alice@example.com")
    alice_conversation = await new_conversation(client)
    await seed_history(app, alice_conversation["id"])

    await login(client, "mallory@example.com")  # the client now acts as mallory
    path = f"/conversations/{alice_conversation['id']}"

    assert (await client.get("/conversations")).json() == []
    # 404, not 403: don't confirm that the id exists.
    assert (await client.get(f"{path}/messages")).status_code == 404
    assert (await client.delete(path)).status_code == 404
    state = await graph_of(app).aget_state(thread_config(uuid.UUID(alice_conversation["id"])))
    assert len(state.values["messages"]) == 3  # untouched


async def test_delete_removes_row_and_checkpoints(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)
    await seed_history(app, conversation["id"])
    path = f"/conversations/{conversation['id']}"

    assert (await client.delete(path)).status_code == 204

    assert (await client.get("/conversations")).json() == []
    assert (await client.get(f"{path}/messages")).status_code == 404
    assert (await client.delete(path)).status_code == 404
    state = await graph_of(app).aget_state(thread_config(uuid.UUID(conversation["id"])))
    assert state.values == {}


async def test_unknown_or_malformed_ids(client: AsyncClient) -> None:
    await login(client)
    assert (await client.get(f"/conversations/{uuid.uuid4()}/messages")).status_code == 404
    assert (await client.get("/conversations/not-a-uuid/messages")).status_code == 422


KC = "g.word_order_svo"


async def new_practice(client: AsyncClient, **body: Any) -> tuple[int, dict[str, Any]]:
    response = await client.post("/conversations", json={"focus_kc_id": KC, **body})
    data: dict[str, Any] = response.json()
    return response.status_code, data


async def test_free_chat_has_no_focus(client: AsyncClient) -> None:
    await login(client)
    conversation = await new_conversation(client)

    assert conversation["focus_kc"] is None
    # An empty JSON body is the same as none.
    response = await client.post("/conversations", json={})
    assert response.status_code == 201
    assert response.json()["focus_kc"] is None


async def test_practice_conversation_is_titled_in_the_ui_locale(
    client: AsyncClient, app: FastAPI
) -> None:
    await login(client)

    status, zh = await new_practice(client, locale="zh-CN")
    assert status == 201
    assert zh["title"] == "练习：基本句子结构（主语 + 谓语）"  # noqa: RUF001 (Chinese punctuation)
    assert zh["focus_kc"] == {
        "id": KC,
        "name_en": "Basic sentence structure (subject + verb)",
        "name_zh": "基本句子结构（主语 + 谓语）",  # noqa: RUF001 (Chinese punctuation)
        "cefr": "A1",
    }
    # Without a locale in the body, the cookie decides; without either, English.
    await seed_history(app, zh["id"])  # started, so the next one is new
    client.cookies.set("NEXT_LOCALE", "zh-CN")
    assert (await new_practice(client))[1]["title"].startswith("练习：")  # noqa: RUF001 (Chinese punctuation)
    listed = (await client.get("/conversations")).json()
    assert [c["focus_kc"]["id"] for c in listed] == [KC, KC]


async def test_unstarted_practice_is_reused(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    status, first = await new_practice(client)
    assert status == 201
    assert first["title"].startswith("Practice: ")

    # Opening the same practice again before saying anything returns to it, even after
    # the tutor's opening.
    thread = thread_config(uuid.UUID(first["id"]))
    await graph_of(app).aupdate_state(thread, {"messages": [AIMessage("Hi!", id="a1")]})
    status, again = await new_practice(client)
    assert (status, again["id"]) == (200, first["id"])

    # Once the learner has replied, it's a new one.
    await graph_of(app).aupdate_state(
        thread, {"messages": [HumanMessage("I like read.", id="h1")]}, as_node="tutor"
    )
    status, fresh = await new_practice(client)
    assert status == 201
    assert fresh["id"] != first["id"]
    assert len((await client.get("/conversations")).json()) == 2


async def test_practice_is_reused_only_for_its_owner(client: AsyncClient) -> None:
    await login(client, "alice@example.com")
    _, alice = await new_practice(client)

    await login(client, "mallory@example.com")
    status, mallory = await new_practice(client)

    assert status == 201
    assert mallory["id"] != alice["id"]


async def test_unknown_kc_is_rejected(client: AsyncClient) -> None:
    await login(client)

    response = await client.post("/conversations", json={"focus_kc_id": "g.no_such_thing"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_kc"
    assert (await client.get("/conversations")).json() == []
