"""Writing (P2 plan §4.2, task 38): submit a text for review, read the history and one
review, delete one, list the fixed tasks.

A submission is reviewed in the background (Q38c): `POST` answers `pending` at once and
the page polls `GET /writing/{id}` until it is `done` or `failed`.
"""

from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.adaptive.kc.catalog import CefrLevel, get_grammar_catalog
from app.adaptive.rules import get_rules
from app.api.errors import api_error
from app.db.models import WritingSubmission
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.memory.service import get_profile
from app.writing import service
from app.writing.prompts import get_writing_prompts
from app.writing.worker import WritingWorker

router = APIRouter(prefix="/writing", tags=["writing"])

# A first cut on the body's size; `service.create` checks words and characters (Q38f).
_MAX_BODY_CHARS = 20_000
EXCERPT_CHARS = 120


def get_worker(request: Request) -> WritingWorker:
    worker: WritingWorker = request.app.state.writing_worker
    return worker


WorkerDep = Annotated[WritingWorker, Depends(get_worker)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KCNameOut(_Out):
    id: str
    name_en: str
    name_zh: str
    cefr: str


class SubmissionOut(_Out):
    id: int
    prompt: str
    text: str
    word_count: int
    status: str
    error_code: str | None
    # Per sentence: index, paragraph, original, corrected (null: unchanged), mistakes.
    corrections: list[dict[str, Any]] | None
    scores: dict[str, Any] | None
    summary: str | None
    words: list[dict[str, Any]] | None
    model: str | None
    from_conversation: bool
    created_at: datetime
    reviewed_at: datetime | None
    # The KCs named in `corrections`, for their names.
    kcs: list[KCNameOut]


class SubmissionBriefOut(_Out):
    id: int
    prompt: str
    excerpt: str
    word_count: int
    status: str
    mistakes: int
    created_at: datetime


class SubmitIn(BaseModel):
    text: str = Field(max_length=_MAX_BODY_CHARS)
    prompt: str = Field(default="", max_length=500)


class PromptOut(_Out):
    id: str
    en: str
    zh: str


class PromptsOut(BaseModel):
    level: CefrLevel
    prompts: list[PromptOut]


def _mistakes(row: WritingSubmission) -> list[dict[str, Any]]:
    return [m for s in row.corrections or [] for m in s["mistakes"]]


def _out(row: WritingSubmission) -> SubmissionOut:
    catalog = get_grammar_catalog()
    kc_ids = dict.fromkeys(m["kc_id"] for m in _mistakes(row))
    kcs = [KCNameOut.model_validate(kc) for kc_id in kc_ids if (kc := catalog.get(kc_id))]
    return SubmissionOut(
        id=row.id,
        prompt=row.prompt,
        text=row.text,
        word_count=row.word_count,
        status=row.status,
        error_code=row.error_code,
        corrections=row.corrections,
        scores=row.scores,
        summary=row.summary,
        words=row.words,
        model=row.model,
        from_conversation=row.conversation_id is not None,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
        kcs=kcs,
    )


def _not_found() -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, "writing_not_found", "writing not found")


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit(
    body: SubmitIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> SubmissionOut:
    """Submit a text for review; poll `GET /writing/{id}` for the result."""
    try:
        row = await service.create(session, user.id, text=body.text, prompt=body.prompt)
    except service.LengthError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"writing_{exc.code}",
            "write 20-800 English words (6000 characters at most)",
        ) from exc
    await session.commit()
    await session.refresh(row)
    worker.submit(row.id, user.id, tenant.id)
    return _out(row)


@router.get("")
async def list_submissions(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[SubmissionBriefOut]:
    """The learner's latest submissions, newest first."""
    rows = await service.recent(session, user.id, limit=limit)
    return [
        SubmissionBriefOut(
            id=row.id,
            prompt=row.prompt,
            excerpt=" ".join(row.text.split())[:EXCERPT_CHARS],
            word_count=row.word_count,
            status=row.status,
            mistakes=len(_mistakes(row)),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/prompts")
async def list_prompts(
    user: CurrentUser,
    session: SessionDep,
    level: CefrLevel | None = None,
) -> PromptsOut:
    """Fixed tasks for a level: the one asked for, else the learner's (A2 before
    placement)."""
    if level is None:
        profile = await get_profile(session, user.id)
        level = cast(
            CefrLevel,
            (profile.cefr_level if profile else None) or get_rules().practice.default_level,
        )
    prompts = get_writing_prompts().by_level[level]
    return PromptsOut(level=level, prompts=[PromptOut.model_validate(p) for p in prompts])


@router.get("/{submission_id}")
async def get_submission(
    submission_id: int, user: CurrentUser, session: SessionDep
) -> SubmissionOut:
    row = await service.get(session, user.id, submission_id)
    if row is None:
        raise _not_found()
    return _out(row)


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_submission(submission_id: int, user: CurrentUser, session: SessionDep) -> Response:
    """Delete it with the evidence it produced; mastery is replayed (Q38e). Words it put
    on the word list stay there: they are removed on the word list."""
    deleted = await service.delete_submission(
        session, user.id, submission_id, rules=get_rules(), catalog=get_grammar_catalog()
    )
    if not deleted:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
