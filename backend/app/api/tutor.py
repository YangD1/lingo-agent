"""The learner's own tutor (ADR 0032): name, looks, and the model and voices that talk
to them. Everything here is the current user's own; members may use it too."""

import uuid
from collections.abc import Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import api_error
from app.api.providers import VoiceOptionOut
from app.db.models import TutorProfile
from app.deps import CurrentTenant, CurrentUser, SessionDep
from app.providers.llm import get_providers_config
from app.providers.realtime_voices import default_realtime_voice, realtime_voice_options
from app.providers.tenant import load_provider_context
from app.providers.tts import Language
from app.providers.tts_voices import VoiceOption
from app.tutor import service
from app.tutor.options import Chain, TutorOptions, ref, tutor_options

router = APIRouter(prefix="/tutor", tags=["tutor"])

Avatar = Literal["cat", "classic", "casual", "sporty", "artsy"]
Choice = Literal["chat_model", "voices", "realtime_model"]


class TutorIn(BaseModel):
    """The whole tutor; a field left out or null follows the defaults."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(max_length=service.MAX_NAME_LENGTH)] | None = None
    avatar: Avatar | None = None
    color: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")] | None = None
    animate: bool = True
    chat_model: Annotated[str, Field(max_length=300)] | None = None
    tts_model: Annotated[str, Field(max_length=300)] | None = None
    voices: dict[Language, Annotated[str, Field(max_length=service.MAX_VOICE_LENGTH)]] = {}
    realtime_model: Annotated[str, Field(max_length=300)] | None = None
    realtime_voice: Annotated[str, Field(max_length=service.MAX_VOICE_LENGTH)] | None = None


class TutorOut(BaseModel):
    name: str | None = None
    avatar: Avatar | None = None
    color: str | None = None
    animate: bool = True
    chat_model: str | None = None
    tts_model: str | None = None
    voices: dict[Language, str] = {}
    realtime_model: str | None = None
    realtime_voice: str | None = None
    # What is shown and said now: the choice, or the default.
    display_name: str = service.DEFAULT_NAME
    display_avatar: Avatar = "cat"
    # Saved choices not applied now (ADR 0032 §3): their model is no longer usable.
    unavailable: list[Choice] = []


class ChainOut(BaseModel):
    models: list[str]  # `<connection>:<model>`, in route order: the first is used now
    provided_by: str | None
    quota_exhausted: bool


class ReadAloudOut(ChainOut):
    # The model voices are picked for (the first in the chain), its catalog (empty:
    # typed in) and what it reads each language with now.
    voice_model: str | None
    voice_options: list[VoiceOptionOut]
    default_voices: dict[Language, str | None]


class RealtimeOut(ChainOut):
    voice_options: dict[str, list[VoiceOptionOut]]  # by model; models with none left out
    default_voices: dict[str, str | None]


class TutorOptionsOut(BaseModel):
    chat: ChainOut
    read_aloud: ReadAloudOut
    realtime: RealtimeOut


@router.get("")
async def get_tutor(user: CurrentUser, tenant: CurrentTenant, session: SessionDep) -> TutorOut:
    profile = await service.get_tutor(session, user.id)
    if profile is None:
        return TutorOut()
    return _tutor_out(profile, await _options(session, tenant.id))


@router.put("")
async def save_tutor(
    body: TutorIn, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> TutorOut:
    options = await _options(session, tenant.id)
    choice = service.TutorChoice(**body.model_dump())
    try:
        profile = await service.save_tutor(session, user.id, tenant.id, choice, options)
    except service.InvalidChoiceError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid_{exc.field}", str(exc)
        ) from exc
    return _tutor_out(profile, options)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_tutor(user: CurrentUser, session: SessionDep) -> Response:
    """Back to the defaults (ADR 0032 §5)."""
    await service.reset_tutor(session, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/options")
async def get_options(tenant: CurrentTenant, session: SessionDep) -> TutorOptionsOut:
    """What the learner may pick now: models of the chains serving them, and voices."""
    config = get_providers_config()
    ctx = await load_provider_context(session, tenant.id)
    options = tutor_options(config, ctx)
    voice_model = options.tts_model
    return TutorOptionsOut(
        chat=_chain_out(options.chat),
        read_aloud=ReadAloudOut(
            **_chain_out(options.read_aloud).model_dump(),
            voice_model=ref(voice_model) if voice_model else None,
            voice_options=_voices_out(options.tts_voices()),
            default_voices=options.tts_default_voices(config, ctx),
        ),
        realtime=RealtimeOut(
            **_chain_out(options.realtime).model_dump(),
            voice_options={
                ref(m): _voices_out(found)
                for m in options.realtime.models
                if (found := realtime_voice_options(m))
            },
            default_voices={ref(m): default_realtime_voice(m) for m in options.realtime.models},
        ),
    )


async def _options(session: SessionDep, tenant_id: uuid.UUID) -> TutorOptions:
    ctx = await load_provider_context(session, tenant_id)
    return tutor_options(get_providers_config(), ctx)


def _tutor_out(profile: TutorProfile, options: TutorOptions) -> TutorOut:
    return TutorOut(
        name=profile.name,
        avatar=profile.avatar,
        color=profile.color,
        animate=profile.animate,
        chat_model=profile.chat_model,
        tts_model=profile.tts_model,
        voices=profile.voices,
        realtime_model=profile.realtime_model,
        realtime_voice=profile.realtime_voice,
        display_name=profile.name or service.DEFAULT_NAME,
        display_avatar=profile.avatar or service.DEFAULT_AVATAR,
        unavailable=service.unavailable(profile, options),
    )


def _chain_out(chain: Chain) -> ChainOut:
    return ChainOut(
        models=chain.refs, provided_by=chain.provided_by, quota_exhausted=chain.quota_exhausted
    )


def _voices_out(options: Sequence[VoiceOption]) -> list[VoiceOptionOut]:
    return [
        VoiceOptionOut(
            id=o.id,
            name=o.name,
            gender=o.gender,
            languages=list(o.languages),
            accent=o.accent,
            note=o.note,
        )
        for o in options
    ]
