import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TenantMember, User
from app.memory import service
from tests.integration.test_chat_api import login, new_conversation


async def ids_of(session: AsyncSession, email: str) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = await session.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    )
    assert tenant_id is not None
    return user_id, tenant_id


async def add_fact(client: AsyncClient, content: str) -> Any:
    response = await client.post("/memories", json={"content": content})
    assert response.status_code == 201, response.text
    return response.json()


async def test_endpoints_require_login(client: AsyncClient) -> None:
    some_id = uuid.uuid4()
    assert (await client.get("/profile")).status_code == 401
    assert (await client.patch("/profile", json={})).status_code == 401
    assert (await client.get("/memories")).status_code == 401
    assert (await client.post("/memories", json={"content": "x"})).status_code == 401
    assert (await client.patch(f"/memories/{some_id}", json={"content": "x"})).status_code == 401
    assert (await client.delete(f"/memories/{some_id}")).status_code == 401
    assert (await client.delete("/memories")).status_code == 401


async def test_profile_starts_empty(client: AsyncClient) -> None:
    await login(client)

    response = await client.get("/profile")

    assert response.status_code == 200
    assert response.json() == {
        "native_language": None,
        "occupation": None,
        "goal": None,
        "target_exam": None,
        "interests": [],
        "daily_minutes": None,
        "explanation_language": None,
        "chat_language": None,
        "chat_language_effective": "zh",
        "cefr_level": None,
        "timezone": None,
        "manual_fields": [],
    }


async def test_patch_profile_changes_only_sent_fields_and_marks_them_manual(
    client: AsyncClient,
) -> None:
    await login(client)
    first = await client.patch(
        "/profile",
        json={
            "occupation": "  nurse ",
            "interests": ["travel", " travel", "", "films"],
            "target_exam": "ielts",
            "timezone": "Asia/Shanghai",
        },
    )
    assert first.status_code == 200, first.text

    second = await client.patch("/profile", json={"occupation": None, "daily_minutes": 20})

    profile = second.json()
    assert profile["occupation"] is None
    assert profile["interests"] == ["travel", "films"]
    assert profile["target_exam"] == "ielts"
    assert profile["timezone"] == "Asia/Shanghai"
    assert profile["daily_minutes"] == 20
    assert profile["manual_fields"] == [
        "daily_minutes",
        "interests",
        "occupation",
        "target_exam",
        "timezone",
    ]
    assert (await client.get("/profile")).json() == profile


async def test_patch_profile_rejects_bad_values(client: AsyncClient) -> None:
    await login(client)
    bodies: list[dict[str, Any]] = [
        {"target_exam": "toeic"},
        {"timezone": "Mars/Olympus"},
        {"daily_minutes": 0},
        {"explanation_language": "fr"},
        {"cefr_level": "C2"},  # set by assessment only
        {"manual_fields": []},
    ]

    for body in bodies:
        response = await client.patch("/profile", json=body)
        assert response.status_code == 422, body


async def test_chat_language_follows_the_level_until_chosen(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    user_id, _ = await ids_of(db_session, "learner@example.com")
    await service.update_profile(db_session, user_id, {"cefr_level": "B2"}, by_learner=False)
    assert (await client.get("/profile")).json()["chat_language_effective"] == "en"

    chosen = await client.patch("/profile", json={"chat_language": "zh"})
    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert (body["chat_language"], body["chat_language_effective"]) == ("zh", "zh")
    assert "chat_language" in body["manual_fields"]

    # null goes back to the level's default.
    reset = (await client.patch("/profile", json={"chat_language": None})).json()
    assert (reset["chat_language"], reset["chat_language_effective"]) == (None, "en")
    assert (await client.patch("/profile", json={"chat_language": "fr"})).status_code == 422


async def test_add_edit_and_list_facts(client: AsyncClient) -> None:
    await login(client)
    created = await add_fact(client, "  Prefers British spelling  ")
    assert created["kind"] == "fact"
    assert created["content"] == "Prefers British spelling"
    assert created["source_conversation_id"] is None
    assert created["source_title"] is None

    edited = await client.patch(
        f"/memories/{created['id']}", json={"content": "Prefers American spelling"}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["content"] == "Prefers American spelling"

    listed = (await client.get("/memories")).json()
    assert [m["content"] for m in listed] == ["Prefers American spelling"]


async def test_list_filters_by_kind_and_shows_source_title(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    user_id, tenant_id = await ids_of(db_session, "learner@example.com")
    await service.add_memory(
        db_session,
        tenant_id=tenant_id,
        user_id=user_id,
        kind="episode",
        content="Practised job interview answers",
        source_conversation_id=uuid.UUID(conversation["id"]),
    )
    await add_fact(client, "Works night shifts")

    episodes = (await client.get("/memories", params={"kind": "episode"})).json()
    facts = (await client.get("/memories", params={"kind": "fact"})).json()

    assert [m["content"] for m in episodes] == ["Practised job interview answers"]
    assert episodes[0]["source_conversation_id"] == conversation["id"]
    assert episodes[0]["source_title"] == conversation["title"]
    assert [m["content"] for m in facts] == ["Works night shifts"]
    assert (await client.get("/memories", params={"kind": "other"})).status_code == 422


async def test_memory_content_is_validated(client: AsyncClient) -> None:
    await login(client)
    fact = await add_fact(client, "Likes jazz")

    for content in ("", "   ", "x" * (service.MAX_CONTENT_LENGTH + 1)):
        assert (await client.post("/memories", json={"content": content})).status_code == 422
        patched = await client.patch(f"/memories/{fact['id']}", json={"content": content})
        assert patched.status_code == 422

    assert (
        await client.post("/memories", json={"content": "a", "kind": "episode"})
    ).status_code == 422


async def test_delete_one_and_all(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    user_id, tenant_id = await ids_of(db_session, "learner@example.com")
    first = await add_fact(client, "Has a cat")
    await add_fact(client, "Lives in Chengdu")
    await service.add_memory(
        db_session,
        tenant_id=tenant_id,
        user_id=user_id,
        kind="episode",
        content="Talked about pets",
    )

    assert (await client.delete(f"/memories/{first['id']}")).status_code == 204
    assert (await client.delete(f"/memories/{first['id']}")).status_code == 404

    only_facts = await client.delete("/memories", params={"kind": "fact"})
    assert only_facts.json() == {"deleted": 1}
    assert [m["kind"] for m in (await client.get("/memories")).json()] == ["episode"]

    everything = await client.delete("/memories")
    assert everything.json() == {"deleted": 1}
    assert (await client.get("/memories")).json() == []


async def test_other_users_memories_are_invisible(client: AsyncClient) -> None:
    await login(client, "a@example.com")
    theirs = await add_fact(client, "Secret of A")
    client.cookies.clear()
    await login(client, "b@example.com")

    assert (await client.get("/memories")).json() == []
    for response in (
        await client.patch(f"/memories/{theirs['id']}", json={"content": "hijacked"}),
        await client.delete(f"/memories/{theirs['id']}"),
    ):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "memory_not_found"
    assert (await client.delete("/memories")).json() == {"deleted": 0}
