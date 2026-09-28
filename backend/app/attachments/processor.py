"""In-process background processing of attachments (ADR 0008 §3).

An upload is stored with status `processing` and returns at once; a task here then
produces its derived text (image reading, transcript, extracted text) and flips it to
`ready` or `failed`. No task queue: the backend runs a single worker (task 11.1), and a
restart only interrupts in-flight work, which `fail_interrupted` marks for a retry.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from app.db.models import Attachment
from app.providers.config import TenantProviderContext
from app.providers.tenant import load_provider_context

logger = logging.getLogger(__name__)

# Concurrent vision calls per process, shared by all attachments (a 50-page scan
# must not fire 50 requests at once).
VISION_CONCURRENCY = 4


@dataclass(frozen=True)
class ProcessingJob:
    attachment_id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    kind: str
    mime_type: str
    filename: str
    data: bytes
    # (done, total), e.g. pages of a scanned PDF; shown by the UI while it polls.
    report_progress: Callable[[int, int], Awaitable[None]]
    # The tenant's connections and routes, loaded when first needed (the request that
    # uploaded the file is long gone, and a background job must not keep its session).
    provider_context: Callable[[], Awaitable[TenantProviderContext]]
    # Hold one slot per vision call: shared by every attachment in the process.
    vision_slots: asyncio.Semaphore


@dataclass(frozen=True)
class ProcessingResult:
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


class ProcessingFailed(Exception):
    """A failure the learner can act on: `code` is shown (localized) in the UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


type Handler = Callable[[ProcessingJob], Awaitable[ProcessingResult]]


class AttachmentProcessor:
    """Runs one task per attachment. Handlers are looked up by MIME type, then kind."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        handlers: Mapping[str, Handler],
        *,
        vision_concurrency: int = VISION_CONCURRENCY,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._handlers = handlers
        self._tasks: set[asyncio.Task[None]] = set()
        # Handlers that call a vision model hold one slot per call.
        self.vision_slots = asyncio.Semaphore(vision_concurrency)

    def schedule(self, attachment_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._run(attachment_id), name=f"attachment-{attachment_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Wait for every scheduled attachment (tests; shutdown uses `stop`)."""
        while self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        """Cancel in-flight work; each task marks its attachment as interrupted."""
        for task in self._tasks:
            task.cancel()
        await self.wait_idle()

    async def _run(self, attachment_id: uuid.UUID) -> None:
        try:
            async with self._sessionmaker() as session:
                attachment = await session.scalar(
                    select(Attachment)
                    .where(Attachment.id == attachment_id)
                    .options(undefer(Attachment.data))
                )
                if attachment is None or attachment.status != "processing":
                    return  # deleted meanwhile, or already handled
                job = self._job(attachment)
            handler = self._handlers.get(job.mime_type) or self._handlers.get(job.kind)
            if handler is None:
                raise ProcessingFailed("unsupported_file_type", "this file type is not supported")
            result = await handler(job)
        except ProcessingFailed as exc:
            await self._finish(attachment_id, status="failed", error=exc.code, message=exc.message)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                await self._finish(
                    attachment_id,
                    status="failed",
                    error="processing_interrupted",
                    message="processing was interrupted; please retry",
                )
            raise
        except Exception:
            logger.exception("processing attachment %s failed", attachment_id)
            await self._finish(
                attachment_id,
                status="failed",
                error="processing_failed",
                message="the file could not be processed",
            )
        else:
            await self._finish(attachment_id, status="ready", text=result.text, meta=result.meta)

    def _job(self, attachment: Attachment) -> ProcessingJob:
        attachment_id = attachment.id

        tenant_id = attachment.tenant_id

        async def report_progress(done: int, total: int) -> None:
            await self._merge_meta(attachment_id, {"progress": {"done": done, "total": total}})

        async def provider_context() -> TenantProviderContext:
            async with self._sessionmaker() as session:
                return await load_provider_context(session, tenant_id)

        return ProcessingJob(
            attachment_id=attachment.id,
            tenant_id=attachment.tenant_id,
            user_id=attachment.user_id,
            conversation_id=attachment.conversation_id,
            kind=attachment.kind,
            mime_type=attachment.mime_type,
            filename=attachment.filename,
            data=attachment.data,
            report_progress=report_progress,
            provider_context=provider_context,
            vision_slots=self.vision_slots,
        )

    async def _merge_meta(self, attachment_id: uuid.UUID, meta: dict[str, Any]) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(Attachment)
                .where(Attachment.id == attachment_id)
                .values(meta=Attachment.meta.op("||")(meta))
            )
            await session.commit()

    async def _finish(
        self,
        attachment_id: uuid.UUID,
        *,
        status: str,
        text: str | None = None,
        meta: dict[str, Any] | None = None,
        error: str | None = None,
        message: str | None = None,
    ) -> None:
        meta = {**(meta or {}), "progress": None}
        if message is not None:
            meta["error_message"] = message
        async with self._sessionmaker() as session:
            await session.execute(
                update(Attachment)
                # Only if still processing: a delete or retry may have raced us.
                .where(Attachment.id == attachment_id, Attachment.status == "processing")
                .values(
                    status=status,
                    text=text,
                    error=error,
                    meta=Attachment.meta.op("||")(meta),
                )
            )
            await session.commit()


async def fail_interrupted(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """At startup: nothing can still be processing, so any such row was cut off."""
    async with sessionmaker() as session:
        result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
            update(Attachment)
            .where(Attachment.status == "processing")
            .values(
                status="failed",
                error="processing_interrupted",
                meta=Attachment.meta.op("||")(
                    {"progress": None, "error_message": "processing was interrupted; please retry"}
                ),
            )
        )
        await session.commit()
    return result.rowcount
