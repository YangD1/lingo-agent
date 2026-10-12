"""What a main account gives each member, per capability (ADR 0031 §4).

A member's model calls on the main account's connections count against one quota per
capability, each with a daily and a monthly cap. `None` is no cap, 0 is none allowed.
Days and months are UTC, like the background budget (ADR 0025).
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

Capability = Literal["text", "tts", "asr", "pronunciation", "realtime"]
CAPABILITIES: tuple[Capability, ...] = get_args(Capability)

# The provider-layer sections each capability covers. Embedding calls aren't metered
# (they record no usage and are tiny); they follow the text capability's switch.
SECTIONS: dict[Capability, tuple[str, ...]] = {
    "text": ("llm", "embedding"),
    "tts": ("tts",),
    "asr": ("asr",),
    "pronunciation": ("pronunciation",),
    "realtime": ("realtime",),
}
CAPABILITY_OF_SECTION: dict[str, Capability] = {
    section: capability for capability, sections in SECTIONS.items() for section in sections
}

# What a cap counts: tokens (input + output), characters, or minutes.
UNITS: dict[Capability, Literal["tokens", "characters", "minutes"]] = {
    "text": "tokens",
    "tts": "characters",
    "asr": "minutes",
    "pronunciation": "minutes",
    "realtime": "minutes",
}

Cap = Annotated[int, Field(ge=0)] | None


class Limit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily: Cap = None
    monthly: Cap = None


class Quotas(BaseModel):
    """A member's quotas; also the main account's template for new members."""

    model_config = ConfigDict(extra="forbid")

    text: Limit = Limit()
    tts: Limit = Limit()
    asr: Limit = Limit()
    pronunciation: Limit = Limit()
    realtime: Limit = Limit()

    def limit(self, capability: Capability) -> Limit:
        limit: Limit = getattr(self, capability)
        return limit


# The template a main account starts with (Q65e).
DEFAULT_QUOTAS = Quotas(
    text=Limit(daily=200_000, monthly=3_000_000),
    tts=Limit(daily=20_000),
    asr=Limit(daily=30),
    pronunciation=Limit(daily=10),
    realtime=Limit(daily=30),
)
