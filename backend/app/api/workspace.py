"""The chat workspace's documents (ADR 0043 §3): opening, reading, editing, going back.

Only the learner's own conversations and documents; the tutor opens and edits them
through its tools (`app/cards/runtime.py`), not here.
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, status
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from app.adaptive.kc.catalog import CefrLevel
from app.api.errors import api_error
from app.chat import service as chat_service
from app.chat.service import ConversationNotFoundError
from app.db.models import Conversation, WorkspaceDoc, WorkspaceDocVersion
from app.deps import CurrentTenant, CurrentUser, SessionDep, per_user
from app.providers.errors import QUOTA_MESSAGE, NoModelConfiguredError
from app.providers.tenant import load_provider_context
from app.workspace import ai, service
from app.workspace.service import Kind, WorkspaceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace"])

# Generous for a pasted article: the service cuts the text to MAX_READING_WORDS.
MAX_INPUT_CHARS = 60_000

_STATUS = {
    service.DocNotFoundError: status.HTTP_404_NOT_FOUND,
    service.SourceNotFoundError: status.HTTP_404_NOT_FOUND,
    service.VersionConflictError: status.HTTP_409_CONFLICT,
    ai.ParagraphNotFoundError: status.HTTP_404_NOT_FOUND,
    ai.SentenceNotFoundError: status.HTTP_404_NOT_FOUND,
}


def _error(exc: WorkspaceError) -> Exception:
    code = _STATUS.get(type(exc), status.HTTP_422_UNPROCESSABLE_CONTENT)
    return api_error(code, exc.code, exc.message)


class DocOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    kind: Kind
    title: str
    source: str
    source_ref: str | None
    created_by: str
    version: int
    truncated: bool
    created_at: datetime
    updated_at: datetime


class VersionOut(BaseModel):
    number: int
    author: str
    reverted_from: int | None
    created_at: datetime
    updated_at: datetime


class DocDetailOut(DocOut):
    # The current version's content: {"paragraphs": [...]} or {"text": "..."}.
    content: dict[str, Any]
    words: int
    versions: list[VersionOut]


class VersionContentOut(VersionOut):
    content: dict[str, Any]


def _doc_out(doc: WorkspaceDoc) -> DocOut:
    return DocOut.model_validate(doc, from_attributes=True)


def _version_out(row: WorkspaceDocVersion) -> VersionOut:
    return VersionOut.model_validate(row, from_attributes=True)


async def _detail(session: SessionDep, doc: WorkspaceDoc) -> DocDetailOut:
    rows = await service.versions(session, doc.id)
    current = next(r for r in rows if r.number == doc.version)
    return DocDetailOut(
        **_doc_out(doc).model_dump(),
        content=current.content,
        words=service.words(doc.kind, current.content),
        versions=[_version_out(r) for r in rows],
    )


async def _conversation(
    session: SessionDep, user: CurrentUser, conversation_id: uuid.UUID
) -> Conversation:
    try:
        return await chat_service.get_owned_conversation(session, user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "conversation_not_found", "conversation not found"
        ) from exc


async def _doc(session: SessionDep, user: CurrentUser, doc_id: uuid.UUID) -> WorkspaceDoc:
    try:
        return await service.get_owned(session, user.id, doc_id)
    except WorkspaceError as exc:
        raise _error(exc) from exc


@router.get("/conversations/{conversation_id}/workspace")
async def list_docs(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[DocOut]:
    conversation = await _conversation(session, user, conversation_id)
    return [_doc_out(d) for d in await service.list_docs(session, conversation.id)]


class CreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    # paste: `text`; article: `article_id` (+ `level`, the rewritten version shown);
    # writing: `writing_id`; blank: a writing document with no text yet.
    source: Literal["paste", "article", "writing", "blank"]
    title: Annotated[str | None, Field(max_length=service.MAX_TITLE_LENGTH)] = None
    text: Annotated[str | None, Field(max_length=MAX_INPUT_CHARS)] = None
    article_id: int | None = None
    level: CefrLevel | None = None
    writing_id: int | None = None


@router.post("/conversations/{conversation_id}/workspace", status_code=status.HTTP_201_CREATED)
async def create_doc(
    conversation_id: uuid.UUID,
    body: CreateIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
) -> DocDetailOut:
    conversation = await _conversation(session, user, conversation_id)
    try:
        match body.source:
            case "paste" if body.text is not None:
                text = service.text_for(body.kind, body.text, body.title)
            case "article" if body.article_id is not None and body.kind == "reading":
                text = await service.article_text(
                    session, tenant.id, body.article_id, body.level, body.title
                )
            case "writing" if body.writing_id is not None and body.kind == "writing":
                text = await service.submission_text(session, user.id, body.writing_id, body.title)
            case "blank" if body.kind == "writing":
                text = service.writing_text("", body.title)
            case _:
                raise WorkspaceError(f"{body.source} needs its field and a matching kind")
        doc = await service.create(session, conversation, body.kind, body.source, text)
    except WorkspaceError as exc:
        raise _error(exc) from exc
    return await _detail(session, doc)


@router.get("/workspace/docs/{doc_id}")
async def get_doc(doc_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> DocDetailOut:
    return await _detail(session, await _doc(session, user, doc_id))


@router.get("/workspace/docs/{doc_id}/versions/{number}")
async def get_version(
    doc_id: uuid.UUID, number: int, user: CurrentUser, session: SessionDep
) -> VersionContentOut:
    doc = await _doc(session, user, doc_id)
    try:
        row = await service.get_version(session, doc, number)
    except WorkspaceError as exc:
        raise _error(exc) from exc
    return VersionContentOut(**_version_out(row).model_dump(), content=row.content)


class SaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The version the edit was made on; another one is current now -> 409.
    base_version: int
    text: Annotated[str | None, Field(max_length=MAX_INPUT_CHARS)] = None
    paragraphs: Annotated[list[str] | None, Field(max_length=service.MAX_PARAGRAPHS)] = None


@router.put("/workspace/docs/{doc_id}/content")
async def save_doc(
    doc_id: uuid.UUID, body: SaveIn, user: CurrentUser, session: SessionDep
) -> DocDetailOut:
    doc = await _doc(session, user, doc_id)
    content: dict[str, Any] = (
        {"paragraphs": body.paragraphs} if doc.kind == "reading" else {"text": body.text}
    )
    try:
        await service.save(session, doc, body.base_version, content)
    except WorkspaceError as exc:
        raise _error(exc) from exc
    return await _detail(session, doc)


class RevertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int


@router.post("/workspace/docs/{doc_id}/revert")
async def revert_doc(
    doc_id: uuid.UUID, body: RevertIn, user: CurrentUser, session: SessionDep
) -> DocDetailOut:
    doc = await _doc(session, user, doc_id)
    try:
        await service.revert(session, doc, body.version)
    except WorkspaceError as exc:
        raise _error(exc) from exc
    return await _detail(session, doc)


class RenameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(max_length=service.MAX_TITLE_LENGTH)]


@router.patch("/workspace/docs/{doc_id}")
async def rename_doc(
    doc_id: uuid.UUID, body: RenameIn, user: CurrentUser, session: SessionDep
) -> DocOut:
    doc = await _doc(session, user, doc_id)
    try:
        return _doc_out(await service.rename(session, doc, body.title))
    except WorkspaceError as exc:
        raise _error(exc) from exc


@router.delete("/workspace/docs/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(doc_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    await service.delete(session, await _doc(session, user, doc_id))


def _no_model(exc: NoModelConfiguredError) -> Exception:
    message = (
        QUOTA_MESSAGE
        if exc.code == "quota_exhausted"
        else "No chat model is configured. Add one in Settings."
    )
    return api_error(status.HTTP_409_CONFLICT, exc.code, message)


def _unavailable() -> Exception:
    return api_error(
        status.HTTP_502_BAD_GATEWAY, "llm_unavailable", "The model is unavailable right now."
    )


class TranslateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Paragraphs of the current version, by position: those scrolled into view.
    paragraphs: Annotated[list[int], Field(min_length=1, max_length=ai.MAX_PARAGRAPHS_PER_REQUEST)]


class ParagraphTranslationOut(BaseModel):
    index: int
    text: str


class TranslationsOut(BaseModel):
    version: int
    translations: list[ParagraphTranslationOut]


@router.post("/workspace/docs/{doc_id}/translate", dependencies=[per_user("chat")])
async def translate_doc(
    doc_id: uuid.UUID,
    body: TranslateIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
) -> TranslationsOut:
    """Paragraphs in Chinese (ADR 0043 §4): made by a model the first time, then kept."""
    doc = await _doc(session, user, doc_id)
    ctx = await load_provider_context(session, tenant.id)
    config: RunnableConfig = {"metadata": {"user_id": str(user.id)}}
    try:
        found = await ai.translate(session, ctx, doc, body.paragraphs, config)
    except WorkspaceError as exc:
        raise _error(exc) from exc
    except NoModelConfiguredError as exc:
        raise _no_model(exc) from exc
    except Exception as exc:
        # Details stay in the server log; vendor errors can echo input.
        logger.exception("translating workspace document %s failed", doc_id)
        raise _unavailable() from exc
    return TranslationsOut(
        version=doc.version,
        translations=[ParagraphTranslationOut(index=i, text=t) for i, t in found.items()],
    )


class AnalyzeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paragraph: int
    sentence: Annotated[str, Field(min_length=1, max_length=ai.MAX_SENTENCE_CHARS)]


class ClauseOut(BaseModel):
    text: str
    role: str


class PhraseOut(BaseModel):
    text: str
    meaning: str


class AnalysisOut(BaseModel):
    main: str
    clauses: list[ClauseOut]
    phrases: list[PhraseOut]
    meaning: str
    tip: str


@router.post("/workspace/docs/{doc_id}/analyze", dependencies=[per_user("chat")])
async def analyze_sentence(
    doc_id: uuid.UUID,
    body: AnalyzeIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
) -> AnalysisOut:
    """How a sentence of the document is built (ADR 0043 §4), once per sentence."""
    doc = await _doc(session, user, doc_id)
    ctx = await load_provider_context(session, tenant.id)
    config: RunnableConfig = {"metadata": {"user_id": str(user.id)}}
    try:
        found = await ai.analyze(session, ctx, doc, body.paragraph, body.sentence, config)
    except WorkspaceError as exc:
        raise _error(exc) from exc
    except NoModelConfiguredError as exc:
        raise _no_model(exc) from exc
    except ai.AnalysisInvalidError as exc:
        raise api_error(
            status.HTTP_502_BAD_GATEWAY,
            "analysis_invalid",
            "The model's analysis didn't fit the sentence. Please try again.",
        ) from exc
    except Exception as exc:
        logger.exception("analysing a sentence of workspace document %s failed", doc_id)
        raise _unavailable() from exc
    return AnalysisOut.model_validate(found)
