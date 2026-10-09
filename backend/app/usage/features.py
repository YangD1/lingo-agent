"""Which model calls each learner-facing feature makes, loaded from `features.yaml`
(ADR 0014). The AI badge in the frontend is driven by this catalog."""

from functools import cache
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.providers.config import Section

FEATURES_PATH = Path(__file__).parent / "features.yaml"

Timing = Literal["now", "background"]
Per = Literal["call", "image", "page"]


class FeaturesError(Exception):
    """features.yaml is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DefaultEstimate(_Strict):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    audio_seconds: float | None = Field(default=None, gt=0)
    characters: int | None = Field(default=None, gt=0)


class FeatureCall(_Strict):
    task: str = Field(min_length=1, max_length=64)
    section: Section = "llm"
    # The route task it runs on; defaults to `task`.
    route: str | None = None
    timing: Timing
    per: Per = "call"
    # False when the call never lands in llm_usage (embeddings aren't recorded).
    history: bool = True
    default: DefaultEstimate

    @property
    def route_task(self) -> str:
        return self.route or self.task

    @model_validator(mode="after")
    def _check(self) -> Self:
        # Speech-to-text is billed by audio length, text-to-speech by characters,
        # everything else by tokens.
        if (self.section == "asr") != (self.default.audio_seconds is not None):
            raise ValueError("audio_seconds is required for asr calls and only for them")
        if (self.section == "tts") != (self.default.characters is not None):
            raise ValueError("characters is required for tts calls and only for them")
        return self


class Feature(_Strict):
    calls: list[FeatureCall] = Field(min_length=1)


class FeatureCatalog(_Strict):
    window: int = Field(ge=1, le=200)
    features: dict[str, Feature] = Field(min_length=1)


def load_features(path: Path = FEATURES_PATH) -> FeatureCatalog:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FeaturesError(f"AI feature catalog not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise FeaturesError(f"AI feature catalog {path} is not valid YAML: {exc}") from exc
    try:
        return FeatureCatalog.model_validate(raw)
    except ValidationError as exc:
        raise FeaturesError(f"invalid AI feature catalog {path}:\n{exc}") from exc


@cache
def get_features() -> FeatureCatalog:
    return load_features()
