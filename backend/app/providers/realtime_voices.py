# ruff: noqa: RUF001 - the vendors' voice notes are Chinese, punctuation included
"""Voices a realtime call model offers, for the learner's tutor (ADR 0032 §3, Q66k).

From the vendors' voice lists, checked 2026-10-12; task 64's smoke test with real
models confirms them. Only voices that suit an English tutor are listed: no dialects,
no foreign-language personas. Gemini Live keeps the vendor's default for now, and
models without an official list (StepFun's newer ones) offer nothing.
"""

from app.providers.config import ResolvedModel
from app.providers.realtime import realtime_target, realtime_vendor
from app.providers.tts import LANGUAGES
from app.providers.tts_voices import Gender, VoiceOption


def _voice(
    id: str, name: str, gender: Gender | None, note: str = "", *, accent: str | None = None
) -> VoiceOption:
    # A realtime model speaks whatever the conversation is in; these voices all read
    # English and Mandarin.
    return VoiceOption(id, name, gender, LANGUAGES, accent, note)


# platform.openai.com realtime guide: no gender or accent per voice is published.
OPENAI: tuple[VoiceOption, ...] = (
    _voice("marin", "Marin", None, "官方推荐，音质最好"),
    _voice("cedar", "Cedar", None, "官方推荐，音质最好"),
    *(
        _voice(v, v.capitalize(), None)
        for v in ("alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
    ),
)

# Model Studio's Omni voice list: qwen3-omni-flash-realtime (default Cherry).
QWEN3_OMNI: tuple[VoiceOption, ...] = (
    _voice("Cherry", "芊悦", "female", "阳光积极、亲切自然（默认）"),
    _voice("Jennifer", "詹妮弗", "female", "电影质感的美语女声", accent="en-US"),
    _voice("Ethan", "晨煦", "male", "阳光温暖，略带北方口音"),
    _voice("Ryan", "甜茶", "male", "节奏拉满，戏感十足"),
    _voice("Katerina", "卡捷琳娜", "female", "御姐，韵律回味十足"),
    _voice("Elias", "墨讲师", None, "讲师风格"),
    _voice("Nofish", "不吃鱼", None, "不会翘舌音的设计师"),
)

# Same list: Qwen3.5-Omni-Realtime and Qwen3.8-Omni-Flash-Realtime (default Tina).
QWEN_OMNI_NEXT: tuple[VoiceOption, ...] = (
    _voice("Tina", "Tina", "female", "（默认）"),
    _voice("Jennifer", "詹妮弗", "female", "美语女声", accent="en-US"),
    _voice("Aiden", "艾登", "male", "美语男声", accent="en-US"),
    _voice("Mione", "Mione", "female", "英式女声", accent="en-GB"),
    _voice("Serena", "苏瑶", "female", "温柔"),
    _voice("Mia", "乖小妹", "female", "温顺乖巧"),
    _voice("Maia", "四月", "female", "知性温柔"),
    _voice("Raymond", "Raymond", "male"),
    _voice("Evan", "Evan", "male"),
    _voice("Ryan", "甜茶", "male", "戏感十足"),
    _voice("Katerina", "卡捷琳娜", "female", "成熟"),
)

# platform.stepfun.com realtime reference: the preset voices of step-audio-2 (the mini
# model needs a matching sentence in its instructions, so it isn't offered).
STEP_AUDIO_2: tuple[VoiceOption, ...] = (
    _voice("qingchunshaonv", "青春少女", "female", "（默认）"),
    _voice("wenrounansheng", "温柔男声", "male"),
    _voice("elegantgentle-female", "高雅女声", "female"),
    _voice("livelybreezy-female", "活力女声", "female"),
)


def realtime_voice_options(model: ResolvedModel) -> tuple[VoiceOption, ...]:
    vendor = realtime_vendor(model)
    name = model.model.lower()
    if vendor == "openai":
        return OPENAI
    if vendor == "qwen":
        if name.startswith(("qwen3.5-omni", "qwen3.8-omni")):
            return QWEN_OMNI_NEXT
        if name.startswith("qwen3-omni"):
            return QWEN3_OMNI
    if vendor == "stepfun" and name == "step-audio-2":
        return STEP_AUDIO_2
    return ()


def default_realtime_voice(model: ResolvedModel) -> str | None:
    """What a call sounds like when the learner picks nothing: the voice we send, else
    the vendor's own default (listed first)."""
    voice = realtime_target(model).voice
    if voice is not None:
        return voice
    options = realtime_voice_options(model)
    return options[0].id if options else None
