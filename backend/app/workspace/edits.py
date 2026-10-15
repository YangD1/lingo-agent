"""The tutor's proposed changes to a writing document (ADR 0043 §5).

A passage is found by its exact text, never by position the model gives: when the
learner decides, each accepted passage must still be in the current text exactly
once, so their own edits meanwhile only stop the items whose passage they changed.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkspaceDoc, WorkspaceEdit
from app.workspace import service

# Recent proposals listed for a document.
LISTED = 20


class EditNotFoundError(service.WorkspaceError):
    code = "workspace_edit_not_found"


class NotWritingError(service.WorkspaceError):
    code = "workspace_not_writing"


@dataclass(frozen=True)
class Item:
    original: str
    replacement: str
    reason: str


@dataclass(frozen=True)
class Proposed:
    edit: WorkspaceEdit | None
    # Why each refused item was refused, for the model: "#2: ..." lines.
    refused: list[str]


def _span(text: str, passage: str) -> tuple[int, int] | None:
    """Where the passage is, if it is there exactly once."""
    start = text.find(passage)
    if start < 0 or text.find(passage, start + 1) >= 0:
        return None
    return start, start + len(passage)


def _text(content: dict[str, Any]) -> str:
    return str(content.get("text", ""))


async def propose(
    session: AsyncSession, doc: WorkspaceDoc, items: Sequence[Item], tool_call_id: str
) -> Proposed:
    """Keep the items that can be found in the current text; commits. The same call
    again finds its proposal (idempotent by tool call id)."""
    if doc.kind != "writing":
        raise NotWritingError("only a writing document can be edited")
    found = await session.scalar(
        select(WorkspaceEdit).where(
            WorkspaceEdit.doc_id == doc.id, WorkspaceEdit.tool_call_id == tool_call_id
        )
    )
    if found is not None:
        return Proposed(found, [])
    text = _text((await service.get_version(session, doc)).content)
    kept: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []
    refused: list[str] = []
    for number, item in enumerate(items, 1):
        span = _span(text, item.original)
        if item.replacement == item.original:
            refused.append(f"#{number}: the replacement is the same as the passage")
        elif span is None:
            where = "not found" if item.original not in text else "found more than once"
            refused.append(f"#{number}: the passage is {where} in the current text")
        elif any(span[0] < end and start < span[1] for start, end in taken):
            refused.append(f"#{number}: overlaps an earlier edit")
        else:
            taken.append(span)
            kept.append(
                {
                    "original": item.original,
                    "replacement": item.replacement,
                    "reason": item.reason.strip(),
                    "status": "pending",
                }
            )
    if not kept:
        return Proposed(None, refused)
    edit = WorkspaceEdit(
        id=uuid.uuid4(),
        doc_id=doc.id,
        tool_call_id=tool_call_id,
        base_version=doc.version,
        items=kept,
    )
    session.add(edit)
    await session.commit()
    return Proposed(edit, refused)


def stale(item: dict[str, Any], text: str) -> bool:
    """A pending item whose passage the current text no longer has exactly once."""
    return item["status"] == "pending" and _span(text, item["original"]) is None


async def list_edits(session: AsyncSession, doc: WorkspaceDoc) -> list[WorkspaceEdit]:
    rows = await session.scalars(
        select(WorkspaceEdit)
        .where(WorkspaceEdit.doc_id == doc.id)
        .order_by(WorkspaceEdit.created_at.desc(), WorkspaceEdit.id)
        .limit(LISTED)
    )
    return list(rows)


async def get_owned(
    session: AsyncSession, user_id: uuid.UUID, edit_id: uuid.UUID
) -> tuple[WorkspaceEdit, WorkspaceDoc]:
    edit = await session.get(WorkspaceEdit, edit_id, with_for_update=True)
    doc = await session.get(WorkspaceDoc, edit.doc_id) if edit else None
    if edit is None or doc is None or doc.user_id != user_id:
        raise EditNotFoundError("no such edit")
    return edit, doc


async def decide(
    session: AsyncSession,
    doc: WorkspaceDoc,
    edit: WorkspaceEdit,
    accept: Sequence[int],
    decline: Sequence[int],
) -> None:
    """Accept and decline items by position; commits. Accepted items still found in the
    current text make one new version, credited to the tutor; a stale one stays
    pending (it can only be declined). Deciding an item again changes nothing."""
    items = [dict(i) for i in edit.items]
    if any(not 0 <= n < len(items) for n in (*accept, *decline)):
        raise service.WorkspaceError("no such item")
    if set(accept) & set(decline):
        raise service.WorkspaceError("an item is both accepted and declined")
    text = _text((await service.get_version(session, doc)).content)
    spans: list[tuple[int, int, str]] = []
    for n in dict.fromkeys(accept):
        item = items[n]
        span = _span(text, item["original"]) if item["status"] == "pending" else None
        if span is None or any(span[0] < e and s < span[1] for s, e, _ in spans):
            continue
        spans.append((*span, item["replacement"]))
        item["status"] = "accepted"
    for n in decline:
        if items[n]["status"] == "pending":
            items[n]["status"] = "declined"
    edit.items = items
    if not spans:
        await session.commit()
        return
    for start, end, replacement in sorted(spans, reverse=True):
        text = text[:start] + replacement + text[end:]
    # One commit with the items' statuses.
    await service.add_version(session, doc, "tutor", service.writing_text(text, "-").content)
