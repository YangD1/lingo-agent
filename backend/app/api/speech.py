"""Server read-aloud (ADR 0028 §3). Without a read-aloud route the browser reads aloud."""

import logging
from typing import Annotated

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.errors import api_error
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.providers.errors import NoModelConfiguredError
from app.providers.tenant import load_provider_context
from app.providers.tts import Language, SpeechSynthesisError, get_tts
from app.services.speech.read_aloud import read_aloud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/speech", tags=["speech"])

# One sentence at a time (the browser splits replies, ADR 0018 §1); long enough for a
# long sentence, short enough that one request can't run up a large bill.
MAX_TEXT_CHARS = 1000


class CapabilitiesOut(BaseModel):
    # The tenant has a read-aloud route: the UI asks the server first.
    tts: bool


class TtsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]
    language: Language
    # The learner's setting (ADR 0018 §2): English 0.6-1.2, Chinese 1.0.
    speed: Annotated[float, Field(ge=0.5, le=1.5)] = 1.0

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text is blank")
        return value


@router.get("/capabilities")
async def capabilities(
    _: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> CapabilitiesOut:
    ctx = await load_provider_context(session, tenant.id)
    try:
        get_tts(ctx)
    except NoModelConfiguredError:
        return CapabilitiesOut(tts=False)
    return CapabilitiesOut(tts=True)


@router.post(
    "/tts",
    response_class=Response,
    responses={
        200: {"content": {"audio/mpeg": {}}},
        409: {"description": "no read-aloud model configured"},
        502: {"description": "every read-aloud model failed"},
    },
)
async def post_tts(
    body: TtsIn, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> Response:
    ctx = await load_provider_context(session, tenant.id)
    try:
        audio = await read_aloud(
            session, ctx, body.text, language=body.language, speed=body.speed, user_id=user.id
        )
    except NoModelConfiguredError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT, exc.code, "No read-aloud model is configured."
        ) from exc
    except SpeechSynthesisError as exc:
        # Details stay in the server log; vendor errors can echo input.
        logger.warning("read-aloud failed for tenant %s: %r", tenant.id, exc.__cause__)
        raise api_error(
            status.HTTP_502_BAD_GATEWAY, "tts_unavailable", "Read-aloud is unavailable right now."
        ) from exc
    return Response(
        audio.audio,
        media_type=audio.mime_type,
        headers={
            "X-Tts-Cached": "1" if audio.cached else "0",
            # Same text, same voice: the browser may keep it for this learner.
            "Cache-Control": "private, max-age=86400",
        },
    )
