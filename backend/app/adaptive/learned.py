"""When a grammar KC counts as learned, and its FSRS review state (ADR 0021 §7).

Replayed from a KC's evidence like BKT itself, so kc_mastery stays a cache: the result
depends only on the evidence and its times, never on the clock. Walking the counted
observations in order:

- progress: formats answered correctly in practice, hours between the first and the
  last correct practice answer, the latest counted mistake in conversation or writing;
- learned: the first observation at which p_mastery >= bkt.mastered and the
  `mastery_gate` thresholds all hold;
- after that, FSRS: the first review is Easy (see FIRST_RATING), then one review per
  practice set (Again if any answer on the KC in it was wrong, else Good), and Again
  for each counted mistake in conversation or writing;
- revoked: when p_mastery falls below bkt.weak, the KC is no longer learned, its FSRS
  state is dropped and the progress counts again from the next observation.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache

import fsrs

from app.adaptive.bkt import Observation, counted, update
from app.adaptive.exercise.formats import FORMATS, SPECS, Format
from app.adaptive.rules import Rules

# The first review, when the KC becomes learned. The gate already needs several
# formats over more than a day, so the card starts in FSRS's review state (about a
# week out) instead of its minutes-apart learning steps, which Good would give.
FIRST_RATING = fsrs.Rating.Easy

# Sources whose mistakes show the learner using the structure on their own.
FREE_USE_SOURCES = frozenset({"chat", "writing"})


@cache
def _scheduler(desired_retention: float) -> fsrs.Scheduler:
    # No fuzzing: replaying the same evidence must give the same due date.
    return fsrs.Scheduler(desired_retention=desired_retention, enable_fuzzing=False)


@dataclass(frozen=True, slots=True)
class Learned:
    formats_passed: tuple[Format, ...]  # in FORMATS order
    correct_span_hours: float
    last_mistake_at: datetime | None
    mastered_at: datetime | None
    # Set exactly when mastered_at is.
    card: fsrs.Card | None


def _passes(obs: Observation) -> Format | None:
    """The format a correct practice answer proves, if any.

    A format is passed by its last kind of evidence: for find_fix, writing the fix,
    not just spotting the error.
    """
    if obs.source != "exercise" or not obs.correct or obs.format not in SPECS:
        return None
    fmt = obs.format  # narrowed to Format by the membership test
    return fmt if obs.evidence == SPECS[fmt].evidence[-1] else None


@dataclass
class _Walk:
    rules: Rules
    formats: set[Format] = field(default_factory=set)
    first_correct: datetime | None = None
    last_correct: datetime | None = None
    last_mistake: datetime | None = None
    mastered_at: datetime | None = None
    card: fsrs.Card | None = None
    # The practice set under review: its id, last answer time, and whether any was wrong.
    group: tuple[str, datetime, bool] | None = None

    def review(self, at: datetime, good: bool, rating: fsrs.Rating | None = None) -> None:
        assert self.card is not None
        rating = rating or (fsrs.Rating.Good if good else fsrs.Rating.Again)
        sched = _scheduler(self.rules.vocab.desired_retention)
        # py-fsrs takes UTC only; times from the database carry the session's zone.
        self.card, _ = sched.review_card(self.card, rating, at.astimezone(UTC))

    def flush(self) -> None:
        if self.group is not None:
            _, at, wrong = self.group
            self.group = None
            if self.card is not None and self.card.last_review is None:
                # The first review: the set that completed the gate.
                self.review(at, True, FIRST_RATING if not wrong else fsrs.Rating.Good)
            else:
                self.review(at, not wrong)

    def span_hours(self) -> float:
        if self.first_correct is None or self.last_correct is None:
            return 0.0
        return (self.last_correct - self.first_correct).total_seconds() / 3600

    def gate_open(self, at: datetime, p: float) -> bool:
        gate = self.rules.mastery_gate
        clean_since = at - timedelta(days=gate.clean_days)
        return (
            p >= self.rules.bkt.mastered
            and len(self.formats) >= gate.min_formats
            and self.span_hours() >= gate.min_span_hours
            and (self.last_mistake is None or self.last_mistake < clean_since)
        )

    def step(self, obs: Observation, p: float) -> None:
        free_mistake = not obs.correct and obs.source in FREE_USE_SOURCES
        if free_mistake:
            self.last_mistake = obs.at
        if fmt := _passes(obs):
            self.formats.add(fmt)
            self.first_correct = self.first_correct or obs.at
            self.last_correct = obs.at

        if self.mastered_at is not None:
            if p < self.rules.bkt.weak:
                self.revoke()
                return
            if obs.source == "exercise" and obs.group is not None:
                if self.group is not None and self.group[0] != obs.group:
                    self.flush()
                if self.group is None:
                    self.group = (obs.group, obs.at, not obs.correct)
                else:
                    self.group = (obs.group, obs.at, self.group[2] or not obs.correct)
            elif obs.source == "exercise" or free_mistake:
                self.flush()
                self.review(obs.at, obs.correct)
            return

        if self.gate_open(obs.at, p):
            self.mastered_at = obs.at
            self.card = fsrs.Card(card_id=0, due=obs.at.astimezone(UTC))
            if obs.source == "exercise" and obs.group is not None:
                # The rest of this set belongs to the same first review.
                self.group = (obs.group, obs.at, False)
            else:
                self.review(obs.at, True, FIRST_RATING)

    def revoke(self) -> None:
        self.mastered_at = None
        self.card = None
        self.group = None
        self.formats = set()
        self.first_correct = self.last_correct = None


def progress(observations: Iterable[Observation], p_init: float, rules: Rules) -> Learned:
    """Learned state of one KC from its full evidence history (BKT steps as `replay`)."""
    walk = _Walk(rules)
    p = p_init
    for obs in counted(observations, rules):
        p = update(p, obs.correct, obs.evidence, rules)
        walk.step(obs, p)
    walk.flush()
    return Learned(
        formats_passed=tuple(f for f in FORMATS if f in walk.formats),
        correct_span_hours=walk.span_hours(),
        last_mistake_at=walk.last_mistake,
        mastered_at=walk.mastered_at,
        card=walk.card,
    )
