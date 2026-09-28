"""Derived-text handlers, keyed by MIME type or kind (ADR 0008 §1).

Images, audio, PDF and DOCX arrive in task 11B.3; until then they fail with
`unsupported_file_type`.
"""

from app.attachments.processor import Handler, ProcessingJob, ProcessingResult

# Past this the text is cut (and the cut recorded) so one file can't flood the context.
MAX_DOCUMENT_CHARS = 200_000


def truncate(text: str) -> ProcessingResult:
    if len(text) <= MAX_DOCUMENT_CHARS:
        return ProcessingResult(text, {"chars": len(text)})
    return ProcessingResult(
        text[:MAX_DOCUMENT_CHARS], {"chars": MAX_DOCUMENT_CHARS, "truncated": True}
    )


async def plain_text(job: ProcessingJob) -> ProcessingResult:
    # The upload was already checked to be NUL-free UTF-8; utf-8-sig drops a BOM.
    return truncate(job.data.decode("utf-8-sig").replace("\r\n", "\n"))


def default_handlers() -> dict[str, Handler]:
    return {"text/plain": plain_text, "text/markdown": plain_text}
