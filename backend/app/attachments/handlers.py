"""Derived-text handlers, keyed by MIME type or kind (ADR 0008 §1)."""

import asyncio

import anyio

from app.attachments.documents import DocumentError, PdfPage, docx_text, split_pdf
from app.attachments.processor import (
    Handler,
    ProcessingFailed,
    ProcessingJob,
    ProcessingResult,
)
from app.attachments.reading import read_image, render_reading, vendor_failure
from app.attachments.sniff import DOCX_MIME
from app.providers.asr import TranscriptionError, get_asr
from app.providers.errors import NoModelConfiguredError

# Past this the text is cut (and the cut recorded) so one file can't flood the context.
MAX_DOCUMENT_CHARS = 200_000


def truncate(text: str, meta: dict[str, object] | None = None) -> ProcessingResult:
    meta = dict(meta or {})
    if len(text) <= MAX_DOCUMENT_CHARS:
        return ProcessingResult(text, {**meta, "chars": len(text)})
    return ProcessingResult(
        text[:MAX_DOCUMENT_CHARS], {**meta, "chars": MAX_DOCUMENT_CHARS, "truncated": True}
    )


async def plain_text(job: ProcessingJob) -> ProcessingResult:
    # The upload was already checked to be NUL-free UTF-8; utf-8-sig drops a BOM.
    return truncate(job.data.decode("utf-8-sig").replace("\r\n", "\n"))


async def image(job: ProcessingJob) -> ProcessingResult:
    reading = await read_image(job, job.data, job.mime_type)
    return ProcessingResult(render_reading(reading), {"reading": reading.model_dump()})


async def audio(job: ProcessingJob) -> ProcessingResult:
    try:
        asr = get_asr(await job.provider_context())
    except NoModelConfiguredError as exc:
        raise ProcessingFailed(
            exc.code, "no speech-to-text model is configured; set it up in Settings"
        ) from exc
    try:
        transcript = await asr.transcribe(
            job.data,
            filename=job.filename,
            mime_type=job.mime_type,
            user_id=job.user_id,
            conversation_id=job.conversation_id,
        )
    except TranscriptionError as exc:
        cause = exc.__cause__ or exc
        raise ProcessingFailed(
            "transcription_failed", f"speech-to-text failed ({vendor_failure(cause)})"
        ) from exc
    meta: dict[str, object] = {}
    if transcript.language:
        meta["language"] = transcript.language
    if transcript.duration_seconds is not None:
        meta["duration_seconds"] = transcript.duration_seconds
    return ProcessingResult(transcript.text, meta)


async def pdf(job: ProcessingJob) -> ProcessingResult:
    try:
        pages = await anyio.to_thread.run_sync(split_pdf, job.data)
    except DocumentError as exc:
        raise ProcessingFailed(exc.code, exc.message) from exc
    scanned = [p for p in pages if p.image is not None]
    readings: dict[int, str] = {}
    if scanned:
        await job.report_progress(0, len(scanned))

        async def read(page: PdfPage) -> None:
            assert page.image is not None
            reading = await read_image(
                job,
                page.image,
                "image/jpeg",
                instruction=f"This is page {page.number} of a scanned document. "
                "Transcribe all of its text faithfully.",
            )
            readings[page.number] = reading.text_in_image.strip() or render_reading(reading)
            await job.report_progress(len(readings), len(scanned))

        # Concurrency is bounded by the shared vision slots inside read_image. If one
        # page fails, the others are cancelled and the whole file can be retried.
        try:
            async with asyncio.TaskGroup() as group:
                for page in scanned:
                    group.create_task(read(page))
        except ExceptionGroup as group_error:
            # Report the learner-facing reason (e.g. no_vision_model), not the group.
            failed = group_error.subgroup(ProcessingFailed)
            if failed is None:
                raise
            raise _first(failed) from group_error
    text = "\n\n".join(
        f"[Page {p.number}]\n{p.text if p.text is not None else readings[p.number]}" for p in pages
    )
    return truncate(text, {"pages": len(pages), "scanned_pages": len(scanned)})


async def word(job: ProcessingJob) -> ProcessingResult:
    try:
        text = await anyio.to_thread.run_sync(docx_text, job.data)
    except DocumentError as exc:
        raise ProcessingFailed(exc.code, exc.message) from exc
    return truncate(text)


def _first(group: BaseExceptionGroup[ProcessingFailed]) -> ProcessingFailed:
    error = group.exceptions[0]
    return _first(error) if isinstance(error, BaseExceptionGroup) else error


def default_handlers() -> dict[str, Handler]:
    return {
        "text/plain": plain_text,
        "text/markdown": plain_text,
        "application/pdf": pdf,
        DOCX_MIME: word,
        "image": image,
        "audio": audio,
    }
