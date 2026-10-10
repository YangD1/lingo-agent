"""Speaking practice scenarios (ADR 0029 §1).

`scenarios.yaml` is hand-reviewed content checked into the repo, like the grammar
catalog, and validated at startup. A conversation without a scenario is free talk.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel

SCENARIOS_PATH = Path(__file__).parent / "scenarios.yaml"
_ID_PATTERN = r"^[a-z][a-z0-9_]*$"


class ScenarioCatalogError(Exception):
    """The scenario file is missing or invalid."""


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_ID_PATTERN, max_length=40)
    title_en: str = Field(min_length=1)
    title_zh: str = Field(min_length=1)
    # [lowest, highest] CEFR level the scenario suits.
    levels: tuple[CefrLevel, CefrLevel]
    # Who speaking_coach plays.
    role: str = Field(min_length=1)
    learner_goal_en: str = Field(min_length=1)
    learner_goal_zh: str = Field(min_length=1)
    # How the coach opens (it speaks first, Q58e).
    opening: str = Field(min_length=1)
    target_expressions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_levels(self) -> Self:
        if rank(self.levels[0]) > rank(self.levels[1]):
            raise ValueError(f"{self.id}: levels must go from lowest to highest")
        return self

    def suits(self, level: CefrLevel) -> bool:
        return rank(self.levels[0]) <= rank(level) <= rank(self.levels[1])


class ScenarioCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenarios: tuple[Scenario, ...] = Field(min_length=1)
    _by_id: dict[str, Scenario] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _index(self) -> Self:
        for scenario in self.scenarios:
            if scenario.id in self._by_id:
                raise ValueError(f"duplicate scenario id {scenario.id}")
            self._by_id[scenario.id] = scenario
        return self

    def get(self, scenario_id: str) -> Scenario | None:
        return self._by_id.get(scenario_id)

    def for_level(self, level: CefrLevel) -> list["ListedScenario"]:
        """Every scenario, those suiting `level` first (ADR 0029 §1: the rest are shown
        folded away); within each group, easiest first, then in file order."""
        listed = [ListedScenario(s, s.suits(level)) for s in self.scenarios]
        return sorted(listed, key=lambda item: (not item.suits, rank(item.scenario.levels[0])))


@dataclass(frozen=True, slots=True)
class ListedScenario:
    scenario: Scenario
    # Within the scenario's level range for this learner.
    suits: bool


def rank(level: CefrLevel) -> int:
    return CEFR_LEVELS.index(level)


def load_scenarios(path: Path = SCENARIOS_PATH) -> ScenarioCatalog:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScenarioCatalogError(f"scenario file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ScenarioCatalogError(f"scenario file {path} is not valid YAML: {exc}") from exc
    try:
        return ScenarioCatalog.model_validate(raw)
    except ValidationError as exc:
        raise ScenarioCatalogError(f"invalid scenario file {path}:\n{exc}") from exc


@cache
def get_scenarios() -> ScenarioCatalog:
    return load_scenarios()
