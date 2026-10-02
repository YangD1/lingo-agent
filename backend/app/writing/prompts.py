"""The fixed writing tasks of `/writing`, by level (Q38d, `prompts.yaml`)."""

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel

_FILE = Path(__file__).with_name("prompts.yaml")


class WritingPrompt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    en: str
    zh: str


class WritingPrompts(BaseModel):
    model_config = ConfigDict(frozen=True)

    by_level: dict[CefrLevel, tuple[WritingPrompt, ...]]

    @model_validator(mode="after")
    def _complete(self) -> "WritingPrompts":
        if missing := [level for level in CEFR_LEVELS if not self.by_level.get(level)]:
            raise ValueError(f"no writing prompts for {missing}")
        ids = [p.id for prompts in self.by_level.values() for p in prompts]
        if len(ids) != len(set(ids)):
            raise ValueError("writing prompt ids repeat")
        return self


@cache
def get_writing_prompts() -> WritingPrompts:
    return WritingPrompts(by_level=yaml.safe_load(_FILE.read_text(encoding="utf-8")))
