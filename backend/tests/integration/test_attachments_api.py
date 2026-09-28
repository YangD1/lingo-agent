import asyncio
import io
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.attachments.processor import (
    AttachmentProcessor,
    ProcessingFailed,
    ProcessingJob,
    ProcessingResult,
    fail_interrupted,
)
from app.db.models import Attachment
from tests.integration.test_chat_api import login, new_conversation


def png(size: tuple[int, int] = (40, 30)) -> bytes:
    out = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    Image.new("RGB", size, "red").save(out, "PNG", exif=exif)
    return out.getvalue()


def processor_of(app: FastAPI) -> AttachmentProcessor:
    processor: AttachmentProcessor = app.state.attachment_processor
    return processor


async def upload(
    client: AsyncClient, conversation_id: str, data: bytes, filename: str = "notes.txt"
) -> Any:
    return await client.post(
        f"/conversations/{conversation_id}/attachments",
        files={"file": (filename, data, "application/octet-stream")},
    )


async def uploaded(client: AsyncClient, conversation_id: str, data: bytes, filename: str) -> Any:
    response = await upload(client, conversation_id, data, filename)
    assert response.status_code == 201, response.text
    return response.json()


async def settled(client: AsyncClient, app: FastAPI, attachment_id: str) -> Any:
    await processor_of(app).wait_idle()
    response = await client.get(f"/attachments/{attachment_id}")
    assert response.status_code == 200
    return response.json()


async def test_endpoints_require_login(client: AsyncClient) -> None:
    some_id = uuid.uuid4()
    assert (await upload(client, str(some_id), b"hi")).status_code == 401
    assert (await client.get(f"/attachments/{some_id}")).status_code == 401
    assert (await client.get(f"/attachments/{some_id}/content")).status_code == 401
    assert (await client.patch(f"/attachments/{some_id}", json={"text": "x"})).status_code == 401
    assert (await client.post(f"/attachments/{some_id}/retry")).status_code == 401
    assert (await client.delete(f"/attachments/{some_id}")).status_code == 401


async def test_text_document_becomes_ready_with_its_text(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)

    created = await uploaded(
        client, conversation["id"], "\ufeffHello\r\n世界\n".encode(), "C:\\docs\\notes.txt"
    )

    assert created["status"] == "processing"
    assert created["kind"] == "document"
    assert created["mime_type"] == "text/plain"
    assert created["filename"] == "notes.txt"
    assert created["sent"] is False
    ready = await settled(client, app, created["id"])
    assert ready["status"] == "ready"
    assert ready["text"] == "Hello\n世界\n"
    assert ready["meta"] == {"chars": 9, "progress": None}


async def test_image_is_reencoded_and_served_safely(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)

    created = await uploaded(client, conversation["id"], png((3200, 1600)), "作业 1.png")

    assert created["kind"] == "image"
    assert created["mime_type"] == "image/jpeg"
    assert created["meta"] == {"width": 1600, "height": 800}
    response = await client.get(f"/attachments/{created['id']}/content")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == (
        "inline; filename*=UTF-8''%E4%BD%9C%E4%B8%9A%201.png"
    )
    assert "private" in response.headers["cache-control"]
    with Image.open(io.BytesIO(response.content)) as decoded:
        assert decoded.format == "JPEG"
        assert not decoded.getexif()
    assert int(created["size_bytes"]) == len(response.content)


async def test_documents_are_downloaded_not_displayed(client: AsyncClient) -> None:
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], b"# notes", "a.md")

    response = await client.get(f"/attachments/{created['id']}/content")

    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.content == b"# notes"


@pytest.mark.parametrize(
    ("data", "filename", "status", "code"),
    [
        (b"<svg/>", "x.svg", 415, "unsupported_file_type"),
        (b"\x89PNG\r\n\x1a\nnot really", "x.png", 422, "invalid_image"),
        # The per-kind limit (images: 5 MB) is checked before decoding.
        (
            b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024),
            "big.png",
            413,
            "attachment_too_large",
        ),
        # The overall cap (20 MB) is checked while reading, before detection.
        (b"%PDF-" + b"\x00" * (20 * 1024 * 1024), "big.pdf", 413, "attachment_too_large"),
    ],
)
async def test_bad_uploads_are_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    data: bytes,
    filename: str,
    status: int,
    code: str,
) -> None:
    await login(client)
    conversation = await new_conversation(client)

    response = await upload(client, conversation["id"], data, filename)

    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    assert await db_session.scalar(select(func.count()).select_from(Attachment)) == 0


async def test_unsent_attachments_per_conversation_are_limited(client: AsyncClient) -> None:
    await login(client)
    conversation = await new_conversation(client)
    for i in range(10):
        await uploaded(client, conversation["id"], b"x", f"{i}.txt")

    response = await upload(client, conversation["id"], b"x", "11.txt")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "attachment_limit"
    other = await new_conversation(client)
    assert (await upload(client, other["id"], b"x", "a.txt")).status_code == 201


async def test_someone_elses_attachment_is_not_found(client: AsyncClient) -> None:
    await login(client, "owner@example.com")
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], b"secret", "a.txt")
    await client.post("/auth/logout")
    await login(client, "intruder@example.com")

    aid = created["id"]
    responses = [
        await client.get(f"/attachments/{aid}"),
        await client.get(f"/attachments/{aid}/content"),
        await client.patch(f"/attachments/{aid}", json={"text": "mine"}),
        await client.post(f"/attachments/{aid}/retry"),
        await client.delete(f"/attachments/{aid}"),
    ]
    assert [r.status_code for r in responses] == [404] * 5
    assert {r.json()["detail"]["code"] for r in responses} == {"attachment_not_found"}
    upload_there = await upload(client, conversation["id"], b"x", "a.txt")
    assert upload_there.status_code == 404
    assert upload_there.json()["detail"]["code"] == "conversation_not_found"


async def mark_sent(db_session: AsyncSession, attachment_id: str) -> None:
    await db_session.execute(
        update(Attachment).where(Attachment.id == uuid.UUID(attachment_id)).values(message_id="m-1")
    )
    await db_session.commit()


async def test_text_can_be_corrected_until_sent(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], b"I goed home", "a.txt")
    await settled(client, app, created["id"])

    response = await client.patch(f"/attachments/{created['id']}", json={"text": "I went home"})

    assert response.status_code == 200
    assert response.json()["text"] == "I went home"
    assert response.json()["meta"]["edited"] is True
    await mark_sent(db_session, created["id"])
    again = await client.patch(f"/attachments/{created['id']}", json={"text": "changed"})
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "attachment_sent"
    deleted = await client.delete(f"/attachments/{created['id']}")
    assert deleted.status_code == 409
    assert (await client.get(f"/attachments/{created['id']}")).json()["sent"] is True


async def test_text_cannot_be_set_while_processing(client: AsyncClient) -> None:
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], b"x", "a.txt")

    response = await client.patch(f"/attachments/{created['id']}", json={"text": "early"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "attachment_not_ready"


async def test_unsent_attachment_can_be_deleted(client: AsyncClient) -> None:
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], b"x", "a.txt")

    assert (await client.delete(f"/attachments/{created['id']}")).status_code == 204
    assert (await client.get(f"/attachments/{created['id']}")).status_code == 404


async def test_failed_attachment_can_be_retried(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)
    # No PDF handler until task 11B.3: processing fails with a code the UI can show.
    created = await uploaded(client, conversation["id"], b"%PDF-1.7\n", "a.pdf")
    failed = await settled(client, app, created["id"])
    assert failed["status"] == "failed"
    assert failed["error"] == "unsupported_file_type"
    assert failed["meta"]["error_message"]

    retried = await client.post(f"/attachments/{created['id']}/retry")

    assert retried.status_code == 200
    assert retried.json()["status"] == "processing"
    assert retried.json()["error"] is None
    assert "error_message" not in retried.json()["meta"]
    assert (await settled(client, app, created["id"]))["status"] == "failed"


async def test_only_failed_attachments_can_retry(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)
    created = await uploaded(client, conversation["id"], b"x", "a.txt")
    await settled(client, app, created["id"])

    response = await client.post(f"/attachments/{created['id']}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "attachment_not_failed"


async def test_deleting_the_conversation_deletes_its_attachments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    await uploaded(client, conversation["id"], b"x", "a.txt")

    assert (await client.delete(f"/conversations/{conversation['id']}")).status_code == 204

    assert await db_session.scalar(select(func.count()).select_from(Attachment)) == 0


async def test_unsent_uploads_expire_after_a_day(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    old_unsent = await uploaded(client, conversation["id"], b"x", "old.txt")
    old_sent = await uploaded(client, conversation["id"], b"x", "sent.txt")
    await mark_sent(db_session, old_sent["id"])
    await db_session.execute(
        text("UPDATE attachments SET created_at = now() - interval '25 hours'")
    )
    await db_session.commit()

    await uploaded(client, conversation["id"], b"x", "new.txt")

    remaining = set(await db_session.scalars(select(Attachment.filename)))
    assert remaining == {"sent.txt", "new.txt"}
    assert old_unsent["id"] not in remaining


# --- the background processor itself ------------------------------------------------


async def stored(
    sessionmaker: async_sessionmaker[AsyncSession], conversation_id: str, mime: str = "text/plain"
) -> uuid.UUID:
    async with sessionmaker() as session:
        row = await session.execute(
            text("SELECT tenant_id, user_id FROM conversations WHERE id = :id"),
            {"id": conversation_id},
        )
        tenant_id, user_id = row.one()
        attachment = Attachment(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=uuid.UUID(conversation_id),
            kind="document",
            mime_type=mime,
            filename="a.txt",
            size_bytes=1,
            sha256="0" * 64,
            data=b"x",
            status="processing",
            meta={"width": 1},
        )
        session.add(attachment)
        await session.commit()
        return attachment.id


async def load(sessionmaker: async_sessionmaker[AsyncSession], attachment_id: uuid.UUID) -> Any:
    async with sessionmaker() as session:
        return await session.get(Attachment, attachment_id)


async def test_processor_records_progress_and_merges_meta(
    client: AsyncClient, app: FastAPI
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    sessionmaker = app.state.sessionmaker
    seen: list[Any] = []

    async def handler(job: ProcessingJob) -> ProcessingResult:
        await job.report_progress(1, 3)
        seen.append((await load(sessionmaker, job.attachment_id)).meta)
        return ProcessingResult("done", {"pages": 3})

    processor = AttachmentProcessor(sessionmaker, {"text/plain": handler})
    attachment_id = await stored(sessionmaker, conversation["id"])
    processor.schedule(attachment_id)
    await processor.wait_idle()

    assert seen == [{"width": 1, "progress": {"done": 1, "total": 3}}]
    done = await load(sessionmaker, attachment_id)
    assert (done.status, done.text, done.error) == ("ready", "done", None)
    assert done.meta == {"width": 1, "pages": 3, "progress": None}


async def test_processor_reports_handler_failures(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)
    sessionmaker = app.state.sessionmaker

    async def refuses(job: ProcessingJob) -> ProcessingResult:
        raise ProcessingFailed("no_vision_model", "configure a vision model")

    async def crashes(job: ProcessingJob) -> ProcessingResult:
        raise RuntimeError("vendor said: sk-secret is invalid")

    processor = AttachmentProcessor(sessionmaker, {"text/plain": refuses, "text/markdown": crashes})
    refused = await stored(sessionmaker, conversation["id"], "text/plain")
    crashed = await stored(sessionmaker, conversation["id"], "text/markdown")
    processor.schedule(refused)
    processor.schedule(crashed)
    await processor.wait_idle()

    a = await load(sessionmaker, refused)
    assert (a.status, a.error, a.meta["error_message"]) == (
        "failed",
        "no_vision_model",
        "configure a vision model",
    )
    b = await load(sessionmaker, crashed)
    assert (b.status, b.error) == ("failed", "processing_failed")
    assert "sk-secret" not in b.meta["error_message"]  # internals stay in the log


async def test_stopping_marks_in_flight_work_as_interrupted(
    client: AsyncClient, app: FastAPI
) -> None:
    await login(client)
    conversation = await new_conversation(client)
    sessionmaker = app.state.sessionmaker
    started = asyncio.Event()

    async def slow(job: ProcessingJob) -> ProcessingResult:
        started.set()
        await asyncio.sleep(60)
        raise AssertionError("not reached")

    processor = AttachmentProcessor(sessionmaker, {"text/plain": slow})
    attachment_id = await stored(sessionmaker, conversation["id"])
    processor.schedule(attachment_id)
    await started.wait()

    await processor.stop()

    a = await load(sessionmaker, attachment_id)
    assert (a.status, a.error) == ("failed", "processing_interrupted")


async def test_startup_fails_rows_left_processing(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    conversation = await new_conversation(client)
    sessionmaker = app.state.sessionmaker
    attachment_id = await stored(sessionmaker, conversation["id"])

    assert await fail_interrupted(sessionmaker) == 1

    a = await load(sessionmaker, attachment_id)
    assert (a.status, a.error) == ("failed", "processing_interrupted")
    assert a.meta["width"] == 1
