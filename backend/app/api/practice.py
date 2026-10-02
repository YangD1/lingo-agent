"""Practice sets (ADR 0021, task 35): start or continue one, read it, answer, report.

An item's key is sent only once it was answered or reported (`views`). Finishing a set,
by answering or by reporting its last open item, starts generating the next one ahead
(`PracticeWorker.prefetch`).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from app.adaptive.exercise import answer as answering
from app.adaptive.exercise import views
from app.adaptive.exercise.formats import (
    ChoiceResponse,
    FindFixResponse,
    Response,
    TextResponse,
)
from app.adaptive.exercise.grading import InvalidResponseError
from app.adaptive.exercise.worker import PracticeWorker, structured_call
from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.api.errors import api_error
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context

router = APIRouter(prefix="/practice", tags=["practice"])

GRADE_TASK = "exercise_grade"


def get_worker(request: Request) -> PracticeWorker:
    worker: PracticeWorker = request.app.state.practice_worker
    return worker


WorkerDep = Annotated[PracticeWorker, Depends(get_worker)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KCNameOut(_Out):
    id: str
    name_en: str
    name_zh: str
    cefr: str


class ResultOut(_Out):
    correct: bool
    response: dict[str, Any]
    feedback: dict[str, Any]
    created_at: datetime


class ItemOut(_Out):
    id: int
    position: int
    kc: KCNameOut
    format: str
    content: dict[str, Any]
    status: str
    from_bank: bool
    answer: dict[str, Any] | None
    result: ResultOut | None


class HowMadeOut(_Out):
    written: int
    from_bank: int
    rejected: int
    writers: list[str]
    reviewers: list[str]


class MasteryOut(_Out):
    p_mastery: float | None
    state: str | None
    learned: bool


class ProgressOut(_Out):
    formats_passed: list[str]
    correct_span_hours: float
    last_mistake_at: datetime | None
    mastered_at: datetime | None
    due: datetime | None


class KCChangeOut(_Out):
    kc: KCNameOut
    items: int
    correct: int
    before: MasteryOut
    after: MasteryOut
    progress: ProgressOut | None


class SummaryOut(_Out):
    total: int
    correct: int
    kcs: list[KCChangeOut]


class SetOut(_Out):
    id: uuid.UUID
    status: str
    # While generating: generating / reviewing / rewriting / filling.
    stage: str | None = None
    origin: str
    focus_kc: KCNameOut | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    items: list[ItemOut]
    how_made: HowMadeOut | None
    # Once the set is done.
    summary: SummaryOut | None


class SetBriefOut(_Out):
    id: uuid.UUID
    status: str
    origin: str
    focus_kc: KCNameOut | None
    created_at: datetime
    finished_at: datetime | None
    total: int
    answered: int
    correct: int


def _set_not_found() -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, "practice_set_not_found", "practice set not found")


async def _set_out(
    session: SessionDep, worker: PracticeWorker, user_id: uuid.UUID, set_id: uuid.UUID
) -> SetOut:
    try:
        view = await views.get_set(
            session, user_id, set_id, rules=get_rules(), catalog=get_grammar_catalog()
        )
    except views.SetNotFoundError as exc:
        raise _set_not_found() from exc
    out = SetOut.model_validate(view)
    if view.status == "generating":
        out.stage = worker.stage(set_id) or "generating"
    return out


class StartIn(BaseModel):
    origin: Literal["dashboard", "learner", "card", "plan", "practice"] = "practice"
    # Practise this grammar point (Q35a).
    kc_id: str | None = Field(default=None, max_length=100)


@router.post("/sets")
async def start(
    body: StartIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> SetOut:
    """Continue the learner's unfinished set, or start one (generated in the background
    when none is waiting: poll until it is no longer `generating`)."""
    try:
        set_id = await worker.start(user.id, tenant.id, body.origin, focus_kc=body.kc_id)
    except ValueError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_kc", "no such grammar point"
        ) from exc
    return await _set_out(session, worker, user.id, set_id)


@router.get("/sets")
async def list_sets(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SetBriefOut]:
    """The learner's latest started sets, newest first."""
    rows = await views.recent_sets(session, user.id, catalog=get_grammar_catalog(), limit=limit)
    return [SetBriefOut.model_validate(r) for r in rows]


@router.get("/sets/{set_id}")
async def get_set(
    set_id: uuid.UUID, user: CurrentUser, session: SessionDep, worker: WorkerDep
) -> SetOut:
    return await _set_out(session, worker, user.id, set_id)


class AnswerIn(BaseModel):
    # choice4: the option chosen.
    choice: str | None = Field(default=None, max_length=500)
    # cloze, transform, translate, rewrite_own: what the learner wrote.
    text: str | None = Field(default=None, max_length=1000)
    # find_fix: the piece picked as wrong, and its fix.
    segment: int | None = Field(default=None, ge=0, le=10)
    fix: str | None = Field(default=None, max_length=500)
    latency_ms: int | None = Field(default=None, ge=0, le=3_600_000)

    def response(self) -> Response:
        if self.segment is not None:
            return FindFixResponse(segment=self.segment, fix=self.fix or "")
        if self.choice is not None:
            return ChoiceResponse(choice=self.choice)
        return TextResponse(text=self.text or "")


class AnsweredOut(BaseModel):
    item: ItemOut
    # This answer finished the set; the set's summary is ready.
    set_done: bool


def _item_not_found() -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, "exercise_not_found", "exercise not found")


async def _item_out(
    session: SessionDep, worker: PracticeWorker, user_id: uuid.UUID, exercise_id: int
) -> tuple[uuid.UUID, ItemOut]:
    set_id = await views.set_of_item(session, user_id, exercise_id)
    out = await _set_out(session, worker, user_id, set_id)
    return set_id, next(i for i in out.items if i.id == exercise_id)


@router.post("/exercises/{exercise_id}/answer")
async def answer(
    exercise_id: int,
    body: AnswerIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> AnsweredOut:
    """Grade the learner's first answer to an item; answering again returns the first
    result. On 503 nothing was stored and the learner can submit again."""
    try:
        response = body.response()
    except ValueError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_response", "empty answer"
        ) from exc
    # llm_usage attributes the grading call to this learner.
    config: RunnableConfig = {"metadata": {"user_id": str(user.id)}, "tags": ["practice"]}
    grade_call = structured_call(
        await load_provider_context(session, tenant.id), config, GRADE_TASK
    )
    try:
        result = await answering.answer(
            session,
            user.id,
            exercise_id,
            response,
            grade_call=grade_call,
            rules=get_rules(),
            catalog=get_grammar_catalog(),
            latency_ms=body.latency_ms,
        )
    except answering.ExerciseNotFoundError as exc:
        raise _item_not_found() from exc
    except answering.NotAnswerableError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "not_answerable", str(exc)) from exc
    except InvalidResponseError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_response", str(exc)
        ) from exc
    except answering.GradingFailedError as exc:
        no_model = isinstance(exc.__cause__, NoModelConfiguredError)
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "no_llm_configured" if no_model else "grading_failed",
            "the answer could not be graded; nothing was saved, submit it again",
        ) from exc
    if result.set_done:
        await worker.prefetch(user.id, tenant.id)
    _, item = await _item_out(session, worker, user.id, exercise_id)
    return AnsweredOut(item=item, set_done=result.set_done)


@router.post("/exercises/{exercise_id}/report")
async def report(
    exercise_id: int,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> AnsweredOut:
    """The learner says the item is wrong: its answer stops counting."""
    try:
        set_done = await answering.report(
            session, user.id, exercise_id, rules=get_rules(), catalog=get_grammar_catalog()
        )
    except answering.ExerciseNotFoundError as exc:
        raise _item_not_found() from exc
    if set_done:
        await worker.prefetch(user.id, tenant.id)
    _, item = await _item_out(session, worker, user.id, exercise_id)
    return AnsweredOut(item=item, set_done=set_done)
