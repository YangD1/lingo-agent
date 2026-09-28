"""Attachments (ADR 0008 §3). Someone else's attachment or conversation is always a 404."""

import uuid
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import api_error
from app.attachments import service
from app.attachments.images import InvalidImage
from app.attachments.processor import AttachmentProcessor
from app.attachments.service import (
    AttachmentNotFoundError,
    AttachmentStateError,
    FileTooLargeError,
    TooManyPendingError,
)
from app.attachments.sniff import UnsupportedFileType
from app.chat.service import ConversationNotFoundError, get_owned_conversation
from app.db.models import Attachment
from app.deps import CurrentUser, SessionDep

router = APIRouter(tags=["attachments"])


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    kind: str
    mime_type: str
    filename: str
    size_bytes: int
    status: str
    # Derived text: image reading, transcript or extracted document text.
    text: str | None
    # Kind-specific details (dimensions, pages, progress, error_message, ...).
    meta: dict[str, Any]
    error: str | None
    sent: bool
    created_at: datetime

    @classmethod
    def of(cls, attachment: Attachment) -> "AttachmentOut":
        return cls.model_validate(
            {
                **{k: getattr(attachment, k) for k in cls.model_fields if k != "sent"},
                "sent": attachment.message_id is not None,
            }
        )


class AttachmentTextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=200_000)]


def _processor(request: Request) -> AttachmentProcessor:
    processor: AttachmentProcessor = request.app.state.attachment_processor
    return processor


def _not_found() -> HTTPException:
    return api_error(status.HTTP_404_NOT_FOUND, "attachment_not_found", "attachment not found")


async def _owned(
    session: SessionDep, user: CurrentUser, attachment_id: uuid.UUID, *, with_data: bool = False
) -> Attachment:
    try:
        return await service.get_owned_attachment(
            session, user.id, attachment_id, with_data=with_data
        )
    except AttachmentNotFoundError as exc:
        raise _not_found() from exc


def _state_error(exc: AttachmentStateError) -> HTTPException:
    return api_error(status.HTTP_409_CONFLICT, exc.code, exc.message)


async def _read_limited(file: UploadFile) -> bytes:
    data = await file.read(service.MAX_UPLOAD_BYTES + 1)
    if len(data) > service.MAX_UPLOAD_BYTES:
        raise api_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "attachment_too_large",
            f"files can be at most {service.MAX_UPLOAD_BYTES // service.MB} MB",
        )
    return data


@router.post(
    "/conversations/{conversation_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "attachment_limit"},
        413: {"description": "attachment_too_large"},
        415: {"description": "unsupported_file_type"},
        422: {"description": "invalid_image"},
    },
)
async def upload_attachment(
    conversation_id: uuid.UUID,
    file: UploadFile,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
) -> AttachmentOut:
    """Store the file and start producing its text; poll `GET /attachments/{id}`."""
    try:
        conversation = await get_owned_conversation(session, user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "conversation_not_found", "conversation not found"
        ) from exc
    data = await _read_limited(file)
    try:
        attachment = await service.create_attachment(
            session, conversation, filename=file.filename, data=data
        )
    except UnsupportedFileType as exc:
        raise api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported_file_type",
            "supported: images (JPEG, PNG, WebP, GIF), audio (WebM, Ogg, MP4/M4A, MP3, WAV), "
            "documents (PDF, DOCX, TXT, MD)",
        ) from exc
    except FileTooLargeError as exc:
        raise api_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "attachment_too_large",
            f"{exc.kind} files can be at most {exc.limit // service.MB} MB",
        ) from exc
    except InvalidImage as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_image", "the image could not be read"
        ) from exc
    except TooManyPendingError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "attachment_limit",
            f"at most {service.MAX_PENDING_PER_CONVERSATION} unsent attachments per conversation",
        ) from exc
    _processor(request).schedule(attachment.id)
    return AttachmentOut.of(attachment)


@router.get("/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> AttachmentOut:
    return AttachmentOut.of(await _owned(session, user, attachment_id))


@router.get(
    "/attachments/{attachment_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_attachment_content(
    attachment_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    attachment = await _owned(session, user, attachment_id, with_data=True)
    # Images and audio play in the page; documents are always downloaded.
    disposition = "attachment" if attachment.kind == "document" else "inline"
    return Response(
        attachment.data,
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(attachment.filename)}",
            # The type was detected by us; never let the browser guess another one.
            "X-Content-Type-Options": "nosniff",
            # Content never changes for an id; only this user may see it.
            "Cache-Control": "private, max-age=86400, immutable",
        },
    )


@router.patch("/attachments/{attachment_id}", responses={409: {"description": "state"}})
async def update_attachment_text(
    attachment_id: uuid.UUID, body: AttachmentTextIn, user: CurrentUser, session: SessionDep
) -> AttachmentOut:
    """Correct the reading or transcript before sending."""
    attachment = await _owned(session, user, attachment_id)
    try:
        attachment = await service.update_text(session, attachment, body.text)
    except AttachmentStateError as exc:
        raise _state_error(exc) from exc
    return AttachmentOut.of(attachment)


@router.post("/attachments/{attachment_id}/retry", responses={409: {"description": "state"}})
async def retry_attachment(
    attachment_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep
) -> AttachmentOut:
    attachment = await _owned(session, user, attachment_id)
    try:
        attachment = await service.retry(session, attachment)
    except AttachmentStateError as exc:
        raise _state_error(exc) from exc
    _processor(request).schedule(attachment.id)
    return AttachmentOut.of(attachment)


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"description": "attachment_sent"}},
)
async def delete_attachment(
    attachment_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    attachment = await _owned(session, user, attachment_id)
    try:
        await service.delete_attachment(session, attachment)
    except AttachmentStateError as exc:
        raise _state_error(exc) from exc
