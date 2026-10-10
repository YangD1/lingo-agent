"""Server read-aloud (ADR 0028 §3) and shadowing (ADR 0028 §5-§6). Without a read-aloud
route the browser reads aloud; without pronunciation assessment shadowing compares a
transcript, and without speech-to-text either there is no shadowing."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Form, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import CursorResult, delete, select

from app.adaptive.rules import get_rules
from app.api.errors import api_error
from app.db.models import PronunciationAttempt
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.providers.asr import get_asr
from app.providers.errors import NoModelConfiguredError
from app.providers.pronunciation import Language as ShadowingLanguage
from app.providers.pronunciation import get_pronunciation
from app.providers.tenant import load_provider_context
from app.providers.tts import LANGUAGES, Language, NoVoiceError, SpeechSynthesisError, get_tts
from app.services.speech.read_aloud import clear_user_audio, read_aloud
from app.services.speech.shadowing import ShadowingError, Source, shadow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/speech", tags=["speech"])

# One sentence at a time (the browser splits replies, ADR 0018 §1); long enough for a
# long sentence, short enough that one request can't run up a large bill.
MAX_TEXT_CHARS = 1000
# Shadowing: 30 s of 16 kHz 16-bit mono WAV is 960 KB; a sentence read in 30 s is far
# shorter than this.
MAX_SHADOWING_BYTES = 1024 * 1024
MAX_REFERENCE_CHARS = 600

# "assessment": scored by pronunciation assessment; "rough": compared with a transcript.
type ShadowingMode = Literal["assessment", "rough"]


class CapabilitiesOut(BaseModel):
    # The tenant has a read-aloud route: the UI asks the server first ...
    tts: bool
    # ... for these languages; the browser reads the others.
    tts_languages: list[Language] = []
    # How shadowing is scored; None: no shadowing (nothing to score it with).
    shadowing: ShadowingMode | None = None


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
    mode: ShadowingMode | None = None
    for mode_, probe in (("assessment", get_pronunciation), ("rough", get_asr)):
        try:
            probe(ctx)
        except NoModelConfiguredError:
            continue
        mode = mode_  # type: ignore[assignment]
        break
    try:
        tts = get_tts(ctx)
    except NoModelConfiguredError:
        return CapabilitiesOut(tts=False, shadowing=mode)
    languages = [lang for lang in LANGUAGES if tts.candidates(lang)]
    return CapabilitiesOut(tts=bool(languages), tts_languages=languages, shadowing=mode)


@router.post(
    "/tts",
    response_class=Response,
    responses={
        200: {"content": {"audio/mpeg": {}}},
        409: {"description": "no read-aloud model (or voice for the language) configured"},
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
    except NoVoiceError as exc:
        raise api_error(
            status.HTTP_409_CONFLICT, "no_tts_voice", "No read-aloud voice for this language."
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


class ClearedOut(BaseModel):
    deleted: int


@router.delete("/tts-cache")
async def clear_tts_cache(user: CurrentUser, session: SessionDep) -> ClearedOut:
    """Delete the read-aloud audio this learner's requests put in the cache (Q54c). The
    next reading of those sentences is synthesized (and billed) again."""
    return ClearedOut(deleted=await clear_user_audio(session, user.id))


class ShadowingOut(BaseModel):
    """One reading of a sentence (ADR 0028 §6). `scores` and phonemes only for an
    assessment; a rough result marks words none / omission / substitution / insertion."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    source_id: str | None
    reference_text: str
    language: str
    mode: ShadowingMode
    # Why a rough result stands in: "not_configured" or "failed" (assessment failed).
    fallback_reason: str | None
    scores: dict[str, Any] | None
    words: list[dict[str, Any]]
    recognized_text: str
    audio_seconds: float
    # It moved the speaking ability.
    counted: bool
    created_at: datetime
    # Words of the sentence the learner says wrong now (assessment only).
    mispronounced: list[str] = []

    @classmethod
    def of(
        cls, attempt: PronunciationAttempt, mispronounced: list[str] | None = None
    ) -> "ShadowingOut":
        return cls.model_validate(
            {
                **{k: getattr(attempt, k) for k in cls.model_fields if hasattr(attempt, k)},
                "mode": "assessment" if attempt.provider == "azure" else "rough",
                "mispronounced": mispronounced or [],
            }
        )


_SHADOWING_STATUS = {
    "invalid_audio": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "no_speech": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "not_configured": status.HTTP_409_CONFLICT,
    "unavailable": status.HTTP_502_BAD_GATEWAY,
}


@router.post(
    "/shadowing",
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "not_configured: no pronunciation or speech-to-text model"},
        413: {"description": "recording_too_large"},
        422: {"description": "invalid_audio (16 kHz mono WAV, at most 30 s) or no_speech"},
        502: {"description": "unavailable: every model failed"},
    },
)
async def post_shadowing(
    file: UploadFile,
    reference_text: Annotated[str, Form(min_length=1, max_length=MAX_REFERENCE_CHARS)],
    language: Annotated[ShadowingLanguage, Form()],
    source: Annotated[Source, Form()],
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    source_id: Annotated[str | None, Form(max_length=64)] = None,
) -> ShadowingOut:
    """Score a recording of the learner reading `reference_text` and keep the result
    (Q56d); the recording itself is not kept."""
    reference = reference_text.strip()
    if not reference:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_reference", "the sentence is blank"
        )
    audio = await file.read(MAX_SHADOWING_BYTES + 1)
    if len(audio) > MAX_SHADOWING_BYTES:
        raise api_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "recording_too_large",
            f"recordings can be at most {MAX_SHADOWING_BYTES // 1024} KB",
        )
    ctx = await load_provider_context(session, tenant.id)
    try:
        outcome = await shadow(
            session,
            ctx,
            user_id=user.id,
            audio=audio,
            reference_text=reference,
            language=language,
            source=source,
            source_id=source_id,
            rules=get_rules(),
            now=datetime.now(UTC),
        )
    except ShadowingError as exc:
        if exc.code == "unavailable":
            logger.warning("shadowing failed for tenant %s: %r", tenant.id, exc.__cause__)
        raise api_error(_SHADOWING_STATUS[exc.code], exc.code, str(exc)) from exc
    return ShadowingOut.of(outcome.attempt, list(outcome.mispronounced))


class ShadowingPage(BaseModel):
    items: list[ShadowingOut]
    # Pass as `before` for the next (older) page; None at the end.
    next_before: datetime | None


@router.get("/shadowing")
async def list_shadowing(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: datetime | None = None,
) -> ShadowingPage:
    """My readings, newest first (Q56d)."""
    query = select(PronunciationAttempt).where(PronunciationAttempt.user_id == user.id)
    if before is not None:
        query = query.where(PronunciationAttempt.created_at < before)
    rows = list(
        await session.scalars(
            query.order_by(PronunciationAttempt.created_at.desc()).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return ShadowingPage(
        items=[ShadowingOut.of(r) for r in rows],
        next_before=rows[-1].created_at if more else None,
    )


@router.delete("/shadowing/{attempt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shadowing(attempt_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    """Delete one reading. Evidence it gave (speaking ability, word marks) stays, like
    other evidence once counted."""
    statement = delete(PronunciationAttempt).where(
        PronunciationAttempt.id == attempt_id, PronunciationAttempt.user_id == user.id
    )
    result: CursorResult[Any] = await session.execute(statement)  # type: ignore[assignment]
    if not result.rowcount:
        raise api_error(status.HTTP_404_NOT_FOUND, "shadowing_not_found", "reading not found")
    await session.commit()


@router.delete("/shadowing")
async def clear_shadowing(user: CurrentUser, session: SessionDep) -> ClearedOut:
    """Delete all my readings."""
    statement = delete(PronunciationAttempt).where(PronunciationAttempt.user_id == user.id)
    result: CursorResult[Any] = await session.execute(statement)  # type: ignore[assignment]
    await session.commit()
    return ClearedOut(deleted=result.rowcount)
