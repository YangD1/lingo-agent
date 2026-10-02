"""Adaptive-engine rules loaded from `rules.yaml` (ADR 0012).

The algorithms in this package take a `Rules` argument and contain no tuning numbers of
their own, so changing a rule never means changing code.
"""

from functools import cache
from pathlib import Path
from typing import Annotated, Literal, Self, get_args

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
    mastered_stability_days: float = Field(default=21, gt=0)
    screening: ScreeningRules


class VocabCefrReference(_Strict):
    basis: int = Field(ge=1)
    thresholds: dict[CefrLevel, int]

    @model_validator(mode="after")
    def _check(self) -> Self:
        levels = CEFR_LEVELS[1:]
        if set(self.thresholds) != set(levels):
            raise ValueError(f"cefr_reference.thresholds needs exactly {list(levels)}")
        counts = [self.thresholds[level] for level in levels]
        if counts != sorted(counts) or counts[-1] > self.basis:
            raise ValueError("cefr_reference.thresholds must rise from A2 to C2, within basis")
        return self


class PlacementVocabRules(_Strict):
    band_size: int = Field(ge=1)
    max_rank: int = Field(ge=1)
    questions: int = Field(ge=1, le=200)
    pseudo_share: Annotated[float, Field(ge=0.0, lt=1.0)]
    steepness: float = Field(gt=0)
    prior_median: float = Field(gt=0)
    prior_log_sd: float = Field(gt=0)
    unreliable_false_alarm: OpenProbability
    mark_known_p: OpenProbability = 0.9
    cefr_reference: VocabCefrReference | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.max_rank % self.band_size:
            raise ValueError("placement.vocab.max_rank must be a multiple of band_size")
        ref = self.cefr_reference
        if ref is not None and (ref.basis % self.band_size or ref.basis > self.max_rank):
            raise ValueError("cefr_reference.basis must be whole bands within max_rank")
        return self


class PlacementGrammarRules(_Strict):
    target_p: OpenProbability
    pick_tolerance: Annotated[float, Field(ge=0.0, lt=1.0)]
    min_items: int = Field(ge=1)
    max_items: int = Field(ge=1, le=100)
    stop_se: float = Field(gt=0)
    prior_sd: float = Field(gt=0)
    cefr_cutpoints: dict[CefrLevel, float]
    calibrated_min_attempts: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.min_items > self.max_items:
            raise ValueError("placement.grammar.min_items must not exceed max_items")
        levels = CEFR_LEVELS[1:]
        if set(self.cefr_cutpoints) != set(levels):
            raise ValueError(f"cefr_cutpoints needs exactly {list(levels)}")
        cuts = [self.cefr_cutpoints[level] for level in levels]
        if cuts != sorted(cuts):
            raise ValueError("cefr_cutpoints must rise from A2 to C2")
        return self


class PlacementRules(_Strict):
    vocab: PlacementVocabRules
    grammar: PlacementGrammarRules


AdvicePriority = Literal[
    "placement",
    "choose_book",
    "vocab_review",
    "grammar_practice",
    "vocab_screen",
    "vocab_learn",
    "retest",
]
AdviceHalf = Literal["vocab_review", "vocab_learn", "grammar_practice"]


class AdviceRules(_Strict):
    max_candidates: int = Field(ge=1, le=20)
    retest_days: int = Field(ge=1)
    grammar_days: int = Field(ge=1)
    max_grammar: int = Field(ge=0)
    priority: dict[AdvicePriority, Annotated[float, Field(gt=0)]]
    half: dict[AdviceHalf, Annotated[float, Field(gt=0)]]

    @model_validator(mode="after")
    def _check(self) -> Self:
        for name, table, keys in (
            ("priority", self.priority, get_args(AdvicePriority)),
            ("half", self.half, get_args(AdviceHalf)),
        ):
            if missing := set(keys) - table.keys():
                raise ValueError(f"advice.{name} is missing {sorted(missing)}")
        return self


class TargetP(_Strict):
    low: OpenProbability
    high: OpenProbability

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.low > self.high:
            raise ValueError("target_p.low must not exceed high")
        return self


class PracticeRules(_Strict):
    set_size: int = Field(ge=1, le=30)
    weak_share: Probability
    max_same_format_run: int = Field(ge=1)
    target_p: TargetP
    rewrite_own_days: int = Field(ge=1)
    max_regenerations: int = Field(ge=0, le=5)
    default_level: CefrLevel
    importance_by_gap: dict[int, Annotated[float, Field(gt=0)]] = Field(min_length=1)
    recent_mistake_days: int = Field(ge=1)
    mistake_half: float = Field(gt=0)
    max_items_per_kc: int = Field(ge=1)
    production_from_p: Probability

    @model_validator(mode="after")
    def _check(self) -> Self:
        gaps = sorted(self.importance_by_gap)
        if gaps != list(range(gaps[0], gaps[-1] + 1)):
            raise ValueError("importance_by_gap keys must be consecutive integers")
        return self


class MasteryGateRules(_Strict):
    # At most the number of practice formats (six, ADR 0021 §1).
    min_formats: int = Field(ge=1, le=6)
    min_span_hours: float = Field(ge=0)
    clean_days: int = Field(ge=0)


class Rules(_Strict):
    version: str = Field(min_length=1, max_length=50)
    bkt: BktRules
    evidence: EvidenceRules
    elo: EloRules
    difficulty: DifficultyRules
    vocab: VocabRules
    placement: PlacementRules
    advice: AdviceRules
    practice: PracticeRules
    mastery_gate: MasteryGateRules


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
