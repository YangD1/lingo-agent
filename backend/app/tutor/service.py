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

DEFAULT_NAME = "JOJO"
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
    pet: bool = True
    # The pet's own reminders in a bubble (ADR 0039 §4).
    nudges: bool = True
    # The tutor's opening the first time the pet is opened in a day (ADR 0041 §5).
    daily_opening: bool = True
    # The tutor opens the chat workspace by itself (ADR 0045 §3).
    workspace_auto_open: bool = True
    # The tutor gives understanding checks by itself (ADR 0046 §4).
    quiz_proactive: bool = True
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
    # It goes into the tutor's prompts: one line of plain text.
    if name is not None and not name.isprintable():
        raise InvalidChoiceError("name", "a name is one line of plain text")
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
        "pet": choice.pet,
        "nudges": choice.nudges,
        "daily_opening": choice.daily_opening,
        "workspace_auto_open": choice.workspace_auto_open,
        "quiz_proactive": choice.quiz_proactive,
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
    for lang, voice in picked.items():
        check_voice(options, choice.tts_model, lang, voice)
    return picked


def check_voice(options: TutorOptions, model: str | None, language: str, voice: str) -> None:
    """`voice` may read `language` on `model`, the read-aloud model in use. Raises
    InvalidChoiceError. Also checks a voice tried on the tutor page before it is saved."""
    in_use = options.tts_model
    if in_use is None or model != ref(in_use):
        raise InvalidChoiceError("tts_model", "voices are picked for the read-aloud model in use")
    if language not in LANGUAGES:
        raise InvalidChoiceError("voices", f"unknown language {language!r}")
    if len(voice) > MAX_VOICE_LENGTH:
        raise InvalidChoiceError("voices", f"at most {MAX_VOICE_LENGTH} characters")
    # A model with a catalog takes only its voices; others take what is typed (§2).
    catalog = options.tts_voices()
    if catalog and not any(o.id == voice and language in o.languages for o in catalog):
        raise InvalidChoiceError("voices", f"{voice!r} is not a {language} voice of this model")


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
