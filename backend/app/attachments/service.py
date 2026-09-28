"""Attachment storage (ADR 0008 §2-3). Someone else's attachment is always "not found"."""

import hashlib
import re
import unicodedata
import uuid
from datetime import timedelta

import anyio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.attachments.images import normalize_image
from app.attachments.sniff import AttachmentKind, detect
from app.db.models import Attachment, Conversation

MB = 1024 * 1024
# Before normalization; the frontend compresses images to well under 1 MB first.
MAX_BYTES: dict[AttachmentKind, int] = {"image": 5 * MB, "audio": 10 * MB, "document": 20 * MB}
MAX_UPLOAD_BYTES = max(MAX_BYTES.values())
# Uploaded but not yet sent, per conversation: bounds what an idle composer can hold.
MAX_PENDING_PER_CONVERSATION = 10
UNSENT_TTL = timedelta(hours=24)


class AttachmentNotFoundError(Exception):
    """Missing *or* owned by someone else: callers must not tell the two apart."""


class FileTooLargeError(Exception):
    def __init__(self, kind: AttachmentKind | None, limit: int) -> None:
        super().__init__(f"file larger than {limit // MB} MB")
        self.kind = kind
        self.limit = limit


class TooManyPendingError(Exception):
    pass


class AttachmentStateError(Exception):
    """The attachment exists but can't do this now (e.g. already sent)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def clean_filename(name: str | None) -> str:
    """Base name only, no control characters, at most 255 characters."""
    base = re.split(r"[/\\]", name or "")[-1]
    base = "".join(c for c in base if unicodedata.category(c)[0] != "C").strip()
    return base[:255] or "file"


async def create_attachment(
    session: AsyncSession, conversation: Conversation, *, filename: str | None, data: bytes
) -> Attachment:
    """Validate and store an upload with status `processing` (the caller schedules it).

    Raises UnsupportedFileType, InvalidImage, FileTooLargeError or TooManyPendingError.
    """
    name = clean_filename(filename)
    detected = detect(data, name)
    if len(data) > MAX_BYTES[detected.kind]:
        raise FileTooLargeError(detected.kind, MAX_BYTES[detected.kind])
    await _delete_expired_unsent(session)
    pending = await session.scalar(
        select(func.count())
        .select_from(Attachment)
        .where(Attachment.conversation_id == conversation.id, Attachment.message_id.is_(None))
    )
    if (pending or 0) >= MAX_PENDING_PER_CONVERSATION:
        raise TooManyPendingError
    mime_type, meta = detected.mime_type, {}
    if detected.kind == "image":
        image = await anyio.to_thread.run_sync(normalize_image, data)
        data, mime_type = image.data, image.mime_type
        meta = {"width": image.width, "height": image.height}
    attachment = Attachment(
        tenant_id=conversation.tenant_id,
        user_id=conversation.user_id,
        conversation_id=conversation.id,
        kind=detected.kind,
        mime_type=mime_type,
        filename=name,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
        status="processing",
        meta=meta,
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return attachment


async def _delete_expired_unsent(session: AsyncSession) -> None:
    # Lazy cleanup on upload instead of a scheduled job (ADR 0008 §2).
    await session.execute(
        delete(Attachment).where(
            Attachment.message_id.is_(None),
            Attachment.created_at < func.now() - UNSENT_TTL,
        )
    )


async def get_owned_attachment(
    session: AsyncSession, user_id: uuid.UUID, attachment_id: uuid.UUID, *, with_data: bool = False
) -> Attachment:
    query = select(Attachment).where(Attachment.id == attachment_id)
    if with_data:
        query = query.options(undefer(Attachment.data))
    attachment = await session.scalar(query)
    if attachment is None or attachment.user_id != user_id:
        raise AttachmentNotFoundError
    return attachment


def _require_unsent(attachment: Attachment) -> None:
    if attachment.message_id is not None:
        # Sent attachments are part of the conversation's history; changing or removing
        # one would silently rewrite what the tutor has already answered.
        raise AttachmentStateError("attachment_sent", "the attachment was already sent")


async def update_text(session: AsyncSession, attachment: Attachment, text: str) -> Attachment:
    """The learner corrects a reading or transcript before sending it."""
    _require_unsent(attachment)
    if attachment.status != "ready":
        raise AttachmentStateError("attachment_not_ready", "the attachment is not ready yet")
    attachment.text = text
    attachment.meta = {**attachment.meta, "edited": True}
    await session.commit()
    await session.refresh(attachment)
    return attachment


async def retry(session: AsyncSession, attachment: Attachment) -> Attachment:
    """Back to `processing` (the caller schedules it again)."""
    if attachment.status != "failed":
        raise AttachmentStateError("attachment_not_failed", "only failed attachments can retry")
    attachment.status = "processing"
    attachment.error = None
    attachment.meta = {k: v for k, v in attachment.meta.items() if k != "error_message"}
    await session.commit()
    await session.refresh(attachment)
    return attachment


async def delete_attachment(session: AsyncSession, attachment: Attachment) -> None:
    _require_unsent(attachment)
    await session.delete(attachment)
    await session.commit()
