"""Reading and saving the learner's tutor (ADR 0032 §2, §5).

A choice is checked against what the learner may use when saved; later it may stop
being usable (a connection removed, the learner left their main account), and then it
is simply not applied (§3): `unavailable` names those choices for the tutor page.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TUTOR_AVATARS, TutorProfile
from app.providers.realtime_voices import realtime_voice_options
from app.providers.tts import LANGUAGES
from app.tutor.options import TutorOptions, ref

DEFAULT_NAME = "Lingo"
DEFAULT_AVATAR = "cat"
MAX_NAME_LENGTH = 40
MAX_VOICE_LENGTH = 200


class InvalidChoiceError(ValueError):
    """A choice the learner may not make now; `field` names it."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class TutorChoice:
    """What a learner sends: every field optional, None follows the settings page."""

    name: str | None = None
    avatar: str | None = None
    color: str | None = None
    animate: bool = True
    chat_model: str | None = None
    tts_model: str | None = None
    voices: dict[str, str] | None = None
    realtime_model: str | None = None
    realtime_voice: str | None = None


async def get_tutor(session: AsyncSession, user_id: uuid.UUID) -> TutorProfile | None:
    return await session.get(TutorProfile, user_id)


async def save_tutor(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    choice: TutorChoice,
    options: TutorOptions,
) -> TutorProfile:
    """Replace the learner's tutor with `choice`. Raises InvalidChoiceError."""
    values = validate(choice, options)
    profile = await session.get(TutorProfile, user_id)
    if profile is None:
        profile = TutorProfile(user_id=user_id, tenant_id=tenant_id)
        session.add(profile)
    for key, value in values.items():
        setattr(profile, key, value)
    await session.commit()
    await session.refresh(profile)
    return profile


async def reset_tutor(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Back to the defaults: the row is deleted. False when there was none."""
    result = await session.execute(delete(TutorProfile).where(TutorProfile.user_id == user_id))
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


def validate(choice: TutorChoice, options: TutorOptions) -> dict[str, Any]:
    name = (choice.name or "").strip() or None
    if name is not None and len(name) > MAX_NAME_LENGTH:
        raise InvalidChoiceError("name", f"at most {MAX_NAME_LENGTH} characters")
    if choice.avatar is not None and choice.avatar not in TUTOR_AVATARS:
        raise InvalidChoiceError("avatar", f"unknown avatar {choice.avatar!r}")
    color = choice.color.lower() if choice.color else None
    if color is not None and not _is_hex_color(color):
        raise InvalidChoiceError("color", "a color looks like #a1b2c3")
    if choice.chat_model is not None and choice.chat_model not in options.chat.refs:
        raise InvalidChoiceError("chat_model", "not a model your conversations can use now")
    voices = _voices(choice, options)
    realtime_voice = _realtime_voice(choice, options)
    return {
        "name": name,
        "avatar": choice.avatar,
        "color": color,
        "animate": choice.animate,
        "chat_model": choice.chat_model,
        "tts_model": choice.tts_model if voices else None,
        "voices": voices,
        "realtime_model": choice.realtime_model,
        "realtime_voice": realtime_voice,
    }


def unavailable(profile: TutorProfile, options: TutorOptions) -> list[str]:
    """Saved choices that aren't applied now (ADR 0032 §3)."""
    out: list[str] = []
    if profile.chat_model and profile.chat_model not in options.chat.refs:
        out.append("chat_model")
    tts = options.tts_model
    if profile.voices and (tts is None or ref(tts) != profile.tts_model):
        out.append("voices")
    if profile.realtime_model and profile.realtime_model not in options.realtime.refs:
        out.append("realtime_model")
    return out


def _voices(choice: TutorChoice, options: TutorOptions) -> dict[str, str]:
    picked = {lang: v.strip() for lang, v in (choice.voices or {}).items() if v and v.strip()}
    if not picked:
        return {}
    model = options.tts_model
    if model is None or choice.tts_model != ref(model):
        raise InvalidChoiceError("tts_model", "voices are picked for the read-aloud model in use")
    catalog = options.tts_voices()
    for lang, voice in picked.items():
        if lang not in LANGUAGES:
            raise InvalidChoiceError("voices", f"unknown language {lang!r}")
        if len(voice) > MAX_VOICE_LENGTH:
            raise InvalidChoiceError("voices", f"at most {MAX_VOICE_LENGTH} characters")
        # A model with a catalog takes only its voices; others take what is typed (§2).
        if catalog and not any(o.id == voice and lang in o.languages for o in catalog):
            raise InvalidChoiceError("voices", f"{voice!r} is not a {lang} voice of this model")
    return picked


def _realtime_voice(choice: TutorChoice, options: TutorOptions) -> str | None:
    if choice.realtime_model is None:
        if choice.realtime_voice:
            raise InvalidChoiceError("realtime_model", "a call voice needs its model")
        return None
    model = options.realtime_model(choice.realtime_model)
    if model is None:
        raise InvalidChoiceError("realtime_model", "not a model your calls can use now")
    voice = (choice.realtime_voice or "").strip() or None
    if voice is None:
        return None
    catalog = realtime_voice_options(model)
    if not catalog:
        raise InvalidChoiceError("realtime_voice", "this model's voice can't be picked")
    if not any(o.id == voice for o in catalog):
        raise InvalidChoiceError("realtime_voice", f"{voice!r} is not a voice of this model")
    return voice


def _is_hex_color(value: str) -> bool:
    return len(value) == 7 and value[0] == "#" and all(c in "0123456789abcdef" for c in value[1:])
