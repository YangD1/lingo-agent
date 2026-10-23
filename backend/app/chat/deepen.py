"""The tenant's limits on the tutor's follow-up segments (ADR 0064 §5).

Stored on `tenants.deepen_settings`; the bounds are the API's, so a stored value can't
make a learner wait without end or a segment run without end.
"""

from pydantic import BaseModel, ConfigDict, Field

MAX_SEGMENTS = 3
FIRST_CHUNK_SECONDS = (5, 60)
TOTAL_SECONDS = (10, 300)
MAX_TOKENS = (256, 8000)


class DeepenSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Off: the tutor isn't offered `continue_deeper` and the rules don't fire either.
    enabled: bool = True
    # Follow-up segments per turn; the last one isn't offered `continue_deeper`.
    max_segments: int = Field(default=1, ge=1, le=MAX_SEGMENTS)
    # A segment with no text this long after it started is given up.
    first_chunk_seconds: int = Field(
        default=15, ge=FIRST_CHUNK_SECONDS[0], le=FIRST_CHUNK_SECONDS[1]
    )
    # A segment is stopped this long after it started; what it wrote is kept.
    total_seconds: int = Field(default=60, ge=TOTAL_SECONDS[0], le=TOTAL_SECONDS[1])
    max_tokens: int = Field(default=1500, ge=MAX_TOKENS[0], le=MAX_TOKENS[1])


DEFAULT_DEEPEN = DeepenSettings()


def deepen_settings(stored: dict[str, object] | None) -> DeepenSettings:
    """The stored settings, or the defaults where a value is missing or out of bounds
    (a row written before a bound changed)."""
    try:
        return DeepenSettings.model_validate(stored or {})
    except ValueError:
        return DEFAULT_DEEPEN
