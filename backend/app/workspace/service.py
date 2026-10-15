"""Workspace documents and their versions (ADR 0043 §3).

A document keeps its own copy of the text it was opened from. Every change is a new
version, except a learner's edits within a few minutes of their last version, which
update it in place (Q83f), so typing does not leave a version per pause.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import CefrLevel
from app.chat.reading import beginning
from app.db.models import (
    ArticleVersion,
    Conversation,
    WorkspaceDoc,
    WorkspaceDocVersion,
    WritingSubmission,
)
from app.services.news import feeds
from app.services.news.clean import count_words
from app.services.news.feeds import FeedError
from app.writing.text import MAX_CHARS as MAX_WRITING_CHARS

type Kind = Literal["reading", "writing"]
type Author = Literal["learner", "tutor"]

# Q83g: a longer reading text is cut, at a paragraph where it can be.
MAX_READING_WORDS = 5000
MAX_PARAGRAPHS = 500
MAX_TITLE_LENGTH = 200
# Untitled documents are named after their beginning, this long.
DERIVED_TITLE_LENGTH = 60
# Q83f: a learner's edits this soon after their latest version update it.
MERGE_WINDOW = timedelta(minutes=5)


class WorkspaceError(ValueError):
    """`code` is the API error code."""

    code = "workspace_invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DocNotFoundError(WorkspaceError):
    code = "workspace_doc_not_found"


class SourceNotFoundError(WorkspaceError):
    code = "workspace_source_not_found"


class VersionConflictError(WorkspaceError):
    """Saved over a version that is no longer the current one (another tab, the tutor)."""

    code = "workspace_version_conflict"


class EmptyTextError(WorkspaceError):
    code = "workspace_empty"


class TooLongError(WorkspaceError):
    code = "workspace_too_long"


@dataclass(frozen=True)
class Text:
    """A document's text before it is stored: `content` as in the version row."""

    content: dict[str, Any]
    title: str
    truncated: bool = False
    source_ref: str | None = None


def paragraphs_of(text: str) -> list[str]:
    """Blocks separated by blank lines; a line break alone joins the lines."""
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    return [re.sub(r"\s+", " ", b).strip() for b in blocks if b.strip()]


def _cut(paragraphs: list[str]) -> tuple[list[str], bool]:
    kept = beginning(paragraphs, MAX_READING_WORDS)[:MAX_PARAGRAPHS]
    if kept and count_words(kept[0]) > MAX_READING_WORDS:
        kept[0] = " ".join(kept[0].split()[:MAX_READING_WORDS])
        return kept, True
    return kept, len(kept) < len(paragraphs)


def _title(title: str | None, text: str) -> str:
    title = " ".join((title or "").split())
    if title:
        return title[:MAX_TITLE_LENGTH]
    first = " ".join(text.split())
    if len(first) <= DERIVED_TITLE_LENGTH:
        return first
    return first[:DERIVED_TITLE_LENGTH].rsplit(" ", 1)[0] + "…"


def reading_text(text: str, title: str | None = None) -> Text:
    paragraphs, truncated = _cut(paragraphs_of(text))
    if not paragraphs:
        raise EmptyTextError("the text is empty")
    return Text({"paragraphs": paragraphs}, _title(title, paragraphs[0]), truncated)


def writing_text(text: str, title: str | None = None) -> Text:
    text = text.replace("\r\n", "\n").strip()
    if len(text) > MAX_WRITING_CHARS:
        raise TooLongError(f"a piece of writing is at most {MAX_WRITING_CHARS} characters")
    return Text({"text": text}, _title(title, text))


def text_for(kind: Kind, text: str, title: str | None = None) -> Text:
    return reading_text(text, title) if kind == "reading" else writing_text(text, title)


async def article_text(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    article_id: int,
    level: CefrLevel | None,
    title: str | None = None,
) -> Text:
    """An article the learner can see, as rewritten for `level` when that version is
    ready, else the original."""
    try:
        view = await feeds.get_article(session, article_id, tenant_id)
    except FeedError as exc:
        raise SourceNotFoundError("no such article") from exc
    version = None
    if level is not None:
        version = await session.scalar(
            select(ArticleVersion).where(
                ArticleVersion.tenant_id == tenant_id,
                ArticleVersion.article_id == article_id,
                ArticleVersion.level == level,
                ArticleVersion.status == "ready",
            )
        )
    if version is not None:
        paragraphs, truncated = _cut(list(version.paragraphs))
        name = version.title or view.article.title
    else:
        paragraphs, truncated = _cut(paragraphs_of(view.article.body))
        name = view.article.title
    if not paragraphs:
        raise EmptyTextError("the article is empty")
    return Text({"paragraphs": paragraphs}, _title(title or name, name), truncated, str(article_id))


async def submission_text(
    session: AsyncSession, user_id: uuid.UUID, submission_id: int, title: str | None = None
) -> Text:
    submission = await session.get(WritingSubmission, submission_id)
    if submission is None or submission.user_id != user_id:
        raise SourceNotFoundError("no such writing")
    text = writing_text(submission.text, title or submission.prompt or None)
    return Text(text.content, text.title, source_ref=str(submission_id))


def _check(kind: str, content: dict[str, Any]) -> dict[str, Any]:
    """A saved version's content, in the shape of its kind."""
    if kind == "reading":
        paragraphs = content.get("paragraphs")
        if not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
            raise WorkspaceError("a reading document is a list of paragraphs")
        return reading_text("\n\n".join(paragraphs), "-").content
    text = content.get("text")
    if not isinstance(text, str):
        raise WorkspaceError("a writing document is a text")
    return writing_text(text, "-").content


async def create(
    session: AsyncSession,
    conversation: Conversation,
    kind: Kind,
    source: str,
    text: Text,
    *,
    created_by: Author = "learner",
    tool_call_id: str | None = None,
) -> WorkspaceDoc:
    doc = WorkspaceDoc(
        id=uuid.uuid4(),
        user_id=conversation.user_id,
        conversation_id=conversation.id,
        kind=kind,
        title=text.title,
        source=source,
        source_ref=text.source_ref,
        created_by=created_by,
        tool_call_id=tool_call_id,
        version=1,
        truncated=text.truncated,
    )
    session.add(doc)
    await session.flush()
    session.add(
        WorkspaceDocVersion(doc_id=doc.id, number=1, author=created_by, content=text.content)
    )
    await session.commit()
    return doc


async def list_docs(session: AsyncSession, conversation_id: uuid.UUID) -> list[WorkspaceDoc]:
    rows = await session.scalars(
        select(WorkspaceDoc)
        .where(WorkspaceDoc.conversation_id == conversation_id)
        .order_by(WorkspaceDoc.created_at, WorkspaceDoc.id)
    )
    return list(rows)


async def get_owned(session: AsyncSession, user_id: uuid.UUID, doc_id: uuid.UUID) -> WorkspaceDoc:
    doc = await session.get(WorkspaceDoc, doc_id)
    if doc is None or doc.user_id != user_id:
        raise DocNotFoundError("no such document")
    return doc


async def versions(session: AsyncSession, doc_id: uuid.UUID) -> list[WorkspaceDocVersion]:
    rows = await session.scalars(
        select(WorkspaceDocVersion)
        .where(WorkspaceDocVersion.doc_id == doc_id)
        .order_by(WorkspaceDocVersion.number)
    )
    return list(rows)


async def get_version(
    session: AsyncSession, doc: WorkspaceDoc, number: int | None = None
) -> WorkspaceDocVersion:
    row = await session.get(WorkspaceDocVersion, (doc.id, number or doc.version))
    if row is None:
        raise DocNotFoundError("no such version")
    return row


async def add_version(
    session: AsyncSession,
    doc: WorkspaceDoc,
    author: Author,
    content: dict[str, Any],
    reverted_from: int | None = None,
) -> WorkspaceDocVersion:
    doc.version += 1
    row = WorkspaceDocVersion(
        doc_id=doc.id,
        number=doc.version,
        author=author,
        content=content,
        reverted_from=reverted_from,
    )
    session.add(row)
    doc.updated_at = datetime.now(UTC)
    await session.commit()
    return row


async def save(
    session: AsyncSession,
    doc: WorkspaceDoc,
    base_version: int,
    content: dict[str, Any],
    now: datetime | None = None,
) -> WorkspaceDocVersion:
    """The learner's edit of the current version (Q83f)."""
    if base_version != doc.version:
        raise VersionConflictError("the document changed since it was loaded")
    content = _check(doc.kind, content)
    latest = await get_version(session, doc)
    if content == latest.content:
        return latest
    now = now or datetime.now(UTC)
    # The first version is what the document was opened with: always kept.
    if (
        latest.number > 1
        and latest.author == "learner"
        and latest.reverted_from is None
        and now - latest.created_at < MERGE_WINDOW
    ):
        latest.content = content
        latest.updated_at = now
        doc.updated_at = now
        await session.commit()
        return latest
    return await add_version(session, doc, "learner", content)


async def revert(session: AsyncSession, doc: WorkspaceDoc, number: int) -> WorkspaceDocVersion:
    """Back to an earlier version, as a new one: no version is ever lost."""
    target = await get_version(session, doc, number)
    if number == doc.version:
        return target
    return await add_version(session, doc, "learner", dict(target.content), reverted_from=number)


async def rename(session: AsyncSession, doc: WorkspaceDoc, title: str) -> WorkspaceDoc:
    title = " ".join(title.split())[:MAX_TITLE_LENGTH]
    if not title:
        raise EmptyTextError("the title is empty")
    doc.title = title
    doc.updated_at = datetime.now(UTC)
    await session.commit()
    return doc


async def delete(session: AsyncSession, doc: WorkspaceDoc) -> None:
    await session.delete(doc)
    await session.commit()


def words(kind: str, content: dict[str, Any]) -> int:
    if kind == "reading":
        return sum(count_words(p) for p in content.get("paragraphs", []))
    return count_words(content.get("text", ""))
