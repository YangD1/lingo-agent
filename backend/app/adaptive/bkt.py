"""Bayesian Knowledge Tracing for grammar KCs (ADR 0010 §2, ADR 0012 §2).

Pure functions over `Rules`. `replay` is the only way mastery is computed: kc_mastery
is a cache of replaying a KC's evidence in order, so a rule change (new parameters,
which severities count, per-turn limits) applies to past evidence too.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel
from app.adaptive.rules import Evidence, Rules, Severity

# Numerical guard, not a tuning rule: in floating point a long run of successes
# reaches exactly 1.0, after which no mistake could lower p_mastery again.
_P_MIN, _P_MAX = 1e-4, 1 - 1e-4


@dataclass(frozen=True, slots=True)
class Observation:
    """One piece of evidence about one KC, as stored in kc_evidence."""

    correct: bool
    evidence: Evidence
    at: datetime
    # The learner turn it came from; observations sharing a turn are capped by
    # `evidence.max_per_turn`. None (e.g. a placement answer) is never capped.
    turn: str | None = None
    # Mistakes only; None for correct observations.
    severity: Severity | None = None
    # Where it came from (kc_evidence.source) and, for practice answers, the item's
    # format and the practice set it belongs to; read by `learned.progress`.
    source: str = "chat"
    format: str | None = None
    group: str | None = None


@dataclass(frozen=True, slots=True)
class Mastery:
    p_mastery: float
    observations: int  # counted observations, after severity and per-turn filtering
    recog_correct: int
    produce_correct: int
    last_evidence_at: datetime | None  # latest evidence of any kind, counted or not


def update(p: float, correct: bool, evidence: Evidence, rules: Rules) -> float:
    """Posterior given one observation, then the chance of learning from it."""
    slip = rules.bkt.p_slip
    guess = rules.bkt.p_guess[evidence]
    if correct:
        known = p * (1 - slip)
        posterior = known / (known + (1 - p) * guess)
    else:
        known = p * slip
        posterior = known / (known + (1 - p) * (1 - guess))
    learned = posterior + (1 - posterior) * rules.bkt.p_learn
    return min(max(learned, _P_MIN), _P_MAX)


def prior(kc_level: CefrLevel, learner_level: CefrLevel | None, rules: Rules) -> float:
    """Initial p_mastery for a KC, from the learner's level when known."""
    if learner_level is None:
        return rules.bkt.prior_unknown_learner[kc_level]
    gap = CEFR_LEVELS.index(learner_level) - CEFR_LEVELS.index(kc_level)
    table = rules.bkt.prior_by_gap
    return table[min(max(gap, min(table)), max(table))]


def is_mastered(p: float, rules: Rules) -> bool:
    return p >= rules.bkt.mastered


def counted(observations: Iterable[Observation], rules: Rules) -> list[Observation]:
    """The observations BKT sees, in time order.

    Mistakes of uncounted severities are dropped; within one turn at most
    `max_per_turn` observations are kept, errors before successes, so one message
    that both misuses and uses a structure counts as a miss.
    """
    kept: list[Observation] = []
    per_turn: dict[str, list[Observation]] = {}
    for obs in sorted(observations, key=lambda o: o.at):
        if not obs.correct and obs.severity not in rules.evidence.counted_severities:
            continue
        if obs.turn is None:
            kept.append(obs)
        else:
            per_turn.setdefault(obs.turn, []).append(obs)
    for group in per_turn.values():
        group.sort(key=lambda o: (o.correct, o.at))
        kept.extend(group[: rules.evidence.max_per_turn])
    kept.sort(key=lambda o: o.at)
    return kept


def replay(observations: Iterable[Observation], p_init: float, rules: Rules) -> Mastery:
    """Mastery of one KC from its full evidence history."""
    history = list(observations)
    p = p_init
    recog = produce = 0
    use = counted(history, rules)
    for obs in use:
        p = update(p, obs.correct, obs.evidence, rules)
        if obs.correct:
            if obs.evidence == "recognition":
                recog += 1
            else:
                produce += 1
    return Mastery(
        p_mastery=p,
        observations=len(use),
        recog_correct=recog,
        produce_correct=produce,
        last_evidence_at=max((o.at for o in history), default=None),
    )
