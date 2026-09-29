"""Placement test (P1 plan §6.2): start or continue, answer, read the state and result.

Questions never carry what would give an answer away (`flow.public`); the result
leaves out the answers themselves, which name the items.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.adaptive.placement.flow import AnswerInput, InvalidAnswerError
from app.api.errors import api_error
from app.deps import CurrentUser, SessionDep
from app.placement import service
from app.placement.service import PlacementRuntime, Status

router = APIRouter(prefix="/placement", tags=["placement"])

Level = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


def get_runtime(request: Request) -> PlacementRuntime:
    runtime: PlacementRuntime = request.app.state.placement
    return runtime


RuntimeDep = Annotated[PlacementRuntime, Depends(get_runtime)]


class QuestionOut(BaseModel):
    id: str
    stage: Literal["vocab", "grammar"]
    index: int
    total: int
    # vocab: "do you know this word?"
    word: str | None = None
    # grammar: a sentence with one blank (___) and four options
    stem: str | None = None
    options: list[str] | None = None


class VocabResultOut(BaseModel):
    size: int
    # Rank at which the learner knows half the words.
    half_known_rank: int
    false_alarm: float
    # False when many pseudo-words were answered "known".
    reliable: bool
    # Rough level from the size alone (Milton 2010); not used for placement.
    reference_cefr: Level | None


class GrammarResultOut(BaseModel):
    ability: float
    standard_error: float
    cefr: Level
    answered: int


class ResultOut(BaseModel):
    cefr: Level  # overall: the grammar level
    vocab: VocabResultOut
    grammar: GrammarResultOut


class PlacementOut(BaseModel):
    id: uuid.UUID
    status: Literal["in_progress", "done", "abandoned"]
    stage: Literal["vocab", "grammar"]
    answered: int
    question: QuestionOut | None
    result: ResultOut | None
    created_at: datetime
    finished_at: datetime | None


def _out(s: Status) -> PlacementOut:
    p = s.placement
    result: dict[str, Any] | None = p.result
    return PlacementOut(
        id=p.id,
        status=p.status,
        stage=p.stage,
        answered=s.answered,
        question=QuestionOut.model_validate(s.question) if s.question else None,
        result=ResultOut.model_validate(result) if result else None,
        created_at=p.created_at,
        finished_at=p.finished_at,
    )


def _not_found() -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, "placement_not_found", "placement test not found")


class StartIn(BaseModel):
    # Abandon the running test, if any, and start over.
    restart: bool = False


@router.post("")
async def start(
    body: StartIn, user: CurrentUser, session: SessionDep, runtime: RuntimeDep
) -> PlacementOut:
    """Continue the running test, or start one."""
    try:
        return _out(await service.start(session, runtime, user.id, restart=body.restart))
    except service.WordsMissingError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "words_not_imported",
            "the word list is not imported; run the ECDICT import first",
        ) from exc


@router.get("/latest")
async def latest(
    user: CurrentUser, session: SessionDep, runtime: RuntimeDep
) -> PlacementOut | None:
    """The most recent test in any state; null if the learner never started one."""
    placement = await service.latest(session, user.id)
    if placement is None:
        return None
    return _out(await service.status(session, runtime, user.id, placement.id))


@router.get("/{session_id}")
async def get_placement(
    session_id: uuid.UUID, user: CurrentUser, session: SessionDep, runtime: RuntimeDep
) -> PlacementOut:
    try:
        return _out(await service.status(session, runtime, user.id, session_id))
    except service.PlacementNotFoundError as exc:
        raise _not_found() from exc


class AnswerIn(BaseModel):
    question_id: str = Field(max_length=20)
    # vocab: whether the learner knows the word
    yes: bool | None = None
    # grammar: index of the chosen option
    choice: int | None = Field(default=None, ge=0, le=3)


@router.post("/{session_id}/answer")
async def answer(
    session_id: uuid.UUID,
    body: AnswerIn,
    user: CurrentUser,
    session: SessionDep,
    runtime: RuntimeDep,
) -> PlacementOut:
    """Answer the current question; the reply holds the next one, or the result.

    Sending the answer to a question already answered again returns the state as is.
    """
    reply: AnswerInput = {"question_id": body.question_id}
    if body.yes is not None:
        reply["yes"] = body.yes
    if body.choice is not None:
        reply["choice"] = body.choice
    try:
        return _out(await service.answer(session, runtime, user.id, session_id, reply))
    except service.PlacementNotFoundError as exc:
        raise _not_found() from exc
    except service.NotInProgressError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT, "placement_not_in_progress", "this test was abandoned"
        ) from exc
    except service.StaleQuestionError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "stale_question",
            "that is not the current question; fetch the test again",
        ) from exc
    except InvalidAnswerError as exc:
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_answer", str(exc)) from exc
