"""The chat workspace's documents (ADR 0043 §3): opening, versions, ownership."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ArticleVersion,
    Tenant,
    User,
    WorkspaceAnnotation,
    WorkspaceDoc,
    WorkspaceDocVersion,
    WritingSubmission,
)
from app.services.news.sources import sync_builtin_feeds
from app.workspace import service
from tests.integration.test_chat_send import login, new_conversation
from tests.integration.test_reading_api import add_article

ARTICLE = "A comet was seen.\n\nIt was bright."


@pytest.fixture(autouse=True)
async def builtin_feeds(db_session: AsyncSession) -> None:
    await sync_builtin_feeds(db_session)
    await db_session.commit()


async def paste(
    client: AsyncClient, conversation_id: str, kind: str = "reading", **body: object
) -> Response:
    return await client.post(
        f"/conversations/{conversation_id}/workspace",
        json={"kind": kind, "source": "paste", "text": ARTICLE, **body},
    )


async def test_endpoints_require_login(client: AsyncClient) -> None:
    some = uuid.uuid4()
    assert (await client.get(f"/conversations/{some}/workspace")).status_code == 401
    assert (await client.get(f"/workspace/docs/{some}")).status_code == 401
    assert (await client.delete(f"/workspace/docs/{some}")).status_code == 401


async def test_a_pasted_text_opens_as_paragraphs(client: AsyncClient) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    response = await paste(client, conversation_id)
    assert response.status_code == 201
    doc = response.json()
    assert doc["kind"] == "reading"
    assert doc["source"] == "paste"
    assert doc["created_by"] == "learner"
    assert doc["title"] == "A comet was seen."
    assert doc["content"] == {"paragraphs": ["A comet was seen.", "It was bright."]}
    assert (doc["version"], doc["words"], doc["truncated"]) == (1, 7, False)
    assert [v["number"] for v in doc["versions"]] == [1]

    listed = (await client.get(f"/conversations/{conversation_id}/workspace")).json()
    assert [d["id"] for d in listed] == [doc["id"]]
    assert "content" not in listed[0]


async def test_a_long_text_is_cut_and_said_so(client: AsyncClient) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    paragraph = " ".join(["word"] * 1000)
    text = "\n\n".join([paragraph] * 6)
    doc = (await paste(client, conversation_id, text=text)).json()
    assert doc["truncated"] is True
    assert doc["words"] == service.MAX_READING_WORDS
    assert len(doc["content"]["paragraphs"]) == 5
    assert doc["title"].endswith("…")


async def test_an_article_opens_at_the_level_shown(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    article_id = await add_article(db_session, "nasa", "Comet", datetime.now(UTC))
    tenant_id = await db_session.scalar(select(Tenant.id))
    db_session.add(
        ArticleVersion(
            tenant_id=tenant_id,
            article_id=article_id,
            level="A2",
            status="ready",
            title="Comet (easy)",
            paragraphs=["Easy one.", "Easy two."],
            word_count=4,
        )
    )
    await db_session.commit()

    url = f"/conversations/{conversation_id}/workspace"
    body = {"kind": "reading", "source": "article", "article_id": article_id}
    easy = (await client.post(url, json={**body, "level": "A2"})).json()
    assert (easy["title"], easy["content"]["paragraphs"]) == (
        "Comet (easy)",
        ["Easy one.", "Easy two."],
    )
    assert easy["source_ref"] == str(article_id)
    # No level (the reading bar): the learner's, here practice.default_level A2.
    mine = (await client.post(url, json=body)).json()
    assert mine["content"] == easy["content"]
    # No B2 version yet: the original.
    b2 = (await client.post(url, json={**body, "level": "B2"})).json()
    assert (b2["title"], b2["content"]["paragraphs"]) == ("Comet", ["One.", "Two."])


async def test_an_article_that_is_not_there_is_not_found(client: AsyncClient) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    response = await client.post(
        f"/conversations/{conversation_id}/workspace",
        json={"kind": "reading", "source": "article", "article_id": 999_999},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "workspace_source_not_found"


async def test_writing_opens_blank_or_from_a_submission(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    url = f"/conversations/{conversation_id}/workspace"
    blank = (await client.post(url, json={"kind": "writing", "source": "blank"})).json()
    assert (blank["content"], blank["title"], blank["words"]) == ({"text": ""}, "", 0)

    user = await db_session.scalar(select(User))
    assert user is not None
    submission = WritingSubmission(
        user_id=user.id, prompt="My weekend", text="I go park.", word_count=3, status="done"
    )
    db_session.add(submission)
    await db_session.commit()
    body = {"kind": "writing", "source": "writing", "writing_id": submission.id}
    doc = (await client.post(url, json=body)).json()
    assert (doc["content"], doc["title"]) == ({"text": "I go park."}, "My weekend")
    assert doc["source_ref"] == str(submission.id)


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "reading", "source": "blank"},
        {"kind": "reading", "source": "paste"},
        {"kind": "writing", "source": "article", "article_id": 1},
        {"kind": "reading", "source": "paste", "text": "   \n\n  "},
    ],
    ids=["blank-reading", "paste-without-text", "article-as-writing", "empty-text"],
)
async def test_a_mismatched_source_is_refused(client: AsyncClient, body: dict[str, object]) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    response = await client.post(f"/conversations/{conversation_id}/workspace", json=body)
    assert response.status_code == 422


async def test_only_the_owner_sees_or_changes_a_document(client: AsyncClient) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    doc_id = (await paste(client, conversation_id)).json()["id"]

    await login(client, "other@example.com")
    assert (await client.get(f"/workspace/docs/{doc_id}")).status_code == 404
    assert (await client.delete(f"/workspace/docs/{doc_id}")).status_code == 404
    response = await client.put(
        f"/workspace/docs/{doc_id}/content", json={"base_version": 1, "paragraphs": ["x"]}
    )
    assert response.status_code == 404
    assert (await client.get(f"/conversations/{conversation_id}/workspace")).status_code == 404
    assert (await paste(client, conversation_id)).status_code == 404


async def save(client: AsyncClient, doc_id: str, base: int, text: str) -> Response:
    return await client.put(
        f"/workspace/docs/{doc_id}/content", json={"base_version": base, "text": text}
    )


async def test_edits_merge_into_a_version_within_minutes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    doc_id = (await paste(client, conversation_id, kind="writing")).json()["id"]

    # The text it was opened with stays version 1.
    first = (await save(client, doc_id, 1, "Draft one.")).json()
    assert first["version"] == 2
    second = (await save(client, doc_id, 2, "Draft one, longer.")).json()
    assert second["version"] == 2
    assert second["content"] == {"text": "Draft one, longer."}
    # The same text again: nothing changes.
    assert (await save(client, doc_id, 2, "Draft one, longer.")).json()["version"] == 2

    # Minutes later: a new version.
    row = await db_session.get(WorkspaceDocVersion, (uuid.UUID(doc_id), 2))
    assert row is not None
    row.created_at = datetime.now(UTC) - service.MERGE_WINDOW - timedelta(seconds=1)
    await db_session.commit()
    third = (await save(client, doc_id, 2, "Draft two.")).json()
    assert third["version"] == 3
    assert [v["number"] for v in third["versions"]] == [1, 2, 3]
    old = (await client.get(f"/workspace/docs/{doc_id}/versions/2")).json()
    assert old["content"] == {"text": "Draft one, longer."}


async def test_saving_over_a_newer_version_conflicts(client: AsyncClient) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    doc_id = (await paste(client, conversation_id, kind="writing")).json()["id"]
    await save(client, doc_id, 1, "Mine.")
    response = await save(client, doc_id, 1, "From a stale tab.")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workspace_version_conflict"


async def test_going_back_adds_a_version(client: AsyncClient) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    doc_id = (await paste(client, conversation_id, kind="writing")).json()["id"]
    await save(client, doc_id, 1, "Changed.")
    back = (await client.post(f"/workspace/docs/{doc_id}/revert", json={"version": 1})).json()
    assert back["version"] == 3
    assert back["content"] == {"text": ARTICLE}
    assert back["versions"][-1]["reverted_from"] == 1
    # Back to the current one: nothing to do.
    same = (await client.post(f"/workspace/docs/{doc_id}/revert", json={"version": 3})).json()
    assert same["version"] == 3
    # A version going back is never merged into by later edits.
    assert (await save(client, doc_id, 3, "Again.")).json()["version"] == 4
    missing = await client.post(f"/workspace/docs/{doc_id}/revert", json={"version": 9})
    assert missing.status_code == 404


async def test_writing_longer_than_a_review_allows_is_refused(client: AsyncClient) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    doc_id = (await paste(client, conversation_id, kind="writing")).json()["id"]
    response = await save(client, doc_id, 1, "x" * 6001)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "workspace_too_long"


async def test_rename_and_delete(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    doc_id = (await paste(client, conversation_id)).json()["id"]
    renamed = await client.patch(f"/workspace/docs/{doc_id}", json={"title": "  Comets  "})
    assert renamed.json()["title"] == "Comets"
    assert (await client.patch(f"/workspace/docs/{doc_id}", json={"title": " "})).status_code == 422

    db_session.add(
        WorkspaceAnnotation(doc_id=uuid.UUID(doc_id), kind="translation", key="k", content={})
    )
    await db_session.commit()
    assert (await client.delete(f"/workspace/docs/{doc_id}")).status_code == 204
    assert (await client.get(f"/workspace/docs/{doc_id}")).status_code == 404
    assert await db_session.scalar(select(func.count()).select_from(WorkspaceAnnotation)) == 0


async def test_documents_go_with_their_conversation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    conversation_id = await new_conversation(client)
    await paste(client, conversation_id)
    assert (await client.delete(f"/conversations/{conversation_id}")).status_code == 204
    for model in (WorkspaceDoc, WorkspaceDocVersion):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
