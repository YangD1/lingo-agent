"""Adaptive-engine rules loaded from `rules.yaml` (ADR 0012).

The algorithms in this package take a `Rules` argument and contain no tuning numbers of
their own, so changing a rule never means changing code.
"""

from functools import cache
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel

Evidence = Literal["recognition", "production"]
EVIDENCE_KINDS: tuple[Evidence, ...] = ("recognition", "production")
Severity = Literal["low", "medium", "high"]
SEVERITIES: tuple[Severity, ...] = ("low", "medium", "high")

RULES_PATH = Path(__file__).parent / "rules.yaml"

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
# Guess and slip must stay strictly inside (0, 1): at 0 or 1 an observation could
# drive p_mastery to a certainty no later evidence can move.
OpenProbability = Annotated[float, Field(gt=0.0, lt=1.0)]


class RulesError(Exception):
    """rules.yaml is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BktRules(_Strict):
    p_learn: Probability
    p_slip: OpenProbability
    p_guess: dict[Evidence, OpenProbability]
    mastered: OpenProbability
    weak: OpenProbability
    prior_by_gap: dict[int, Probability] = Field(min_length=1)
    prior_unknown_learner: dict[CefrLevel, Probability]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if missing := set(EVIDENCE_KINDS) - self.p_guess.keys():
            raise ValueError(f"p_guess is missing {sorted(missing)}")
        for kind, guess in self.p_guess.items():
            # Otherwise a correct answer would count as evidence of NOT knowing.
            if guess + self.p_slip >= 1:
                raise ValueError(f"p_guess[{kind}] + p_slip must be below 1")
        gaps = sorted(self.prior_by_gap)
        if gaps != list(range(gaps[0], gaps[-1] + 1)):
            raise ValueError("prior_by_gap keys must be consecutive integers")
        if unset := set(CEFR_LEVELS) - self.prior_unknown_learner.keys():
            raise ValueError(f"prior_unknown_learner is missing {sorted(unset)}")
        if self.weak >= self.mastered:
            raise ValueError("weak must be below mastered")
        return self


class EvidenceRules(_Strict):
    counted_severities: frozenset[Severity]
    max_per_turn: int = Field(ge=1)


class EloK(_Strict):
    alpha: float = Field(gt=0)
    beta: float = Field(ge=0)


class EloRules(_Strict):
    learner: EloK
    item: EloK
    initial_ability: float
    guess_by_format: dict[str, Annotated[float, Field(ge=0.0, lt=1.0)]]


class DifficultyLevel(_Strict):
    offset: float
    description: str = Field(min_length=1)


class DifficultyDimension(_Strict):
    description: str = Field(min_length=1)
    levels: dict[str, DifficultyLevel] = Field(min_length=2)


class DifficultyRules(_Strict):
    cefr_anchor: dict[CefrLevel, float]
    dimensions: dict[str, DifficultyDimension] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if missing := set(CEFR_LEVELS) - self.cefr_anchor.keys():
            raise ValueError(f"cefr_anchor is missing {sorted(missing)}")
        anchors = [self.cefr_anchor[level] for level in CEFR_LEVELS]
        if anchors != sorted(anchors):
            raise ValueError("cefr_anchor must not decrease from A1 to C2")
        return self


class ScreeningRules(_Strict):
    batch_size: int = Field(ge=1, le=200)
    window: int = Field(ge=1)
    skip_ratio: Probability

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.window < self.batch_size:
            raise ValueError("screening.window must be at least batch_size")
        return self


class VocabRules(_Strict):
    desired_retention: OpenProbability
    daily_new: int = Field(ge=0, le=200)
    learn_ahead_minutes: int = Field(ge=0, le=24 * 60)
    screening: ScreeningRules


class Rules(_Strict):
    version: str = Field(min_length=1, max_length=50)
    bkt: BktRules
    evidence: EvidenceRules
    elo: EloRules
    difficulty: DifficultyRules
    vocab: VocabRules


def load_rules(path: Path = RULES_PATH) -> Rules:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RulesError(f"adaptive rules not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise RulesError(f"adaptive rules {path} are not valid YAML: {exc}") from exc
    try:
        return Rules.model_validate(raw)
    except ValidationError as exc:
        raise RulesError(f"invalid adaptive rules {path}:\n{exc}") from exc


@cache
def get_rules() -> Rules:
    return load_rules()
