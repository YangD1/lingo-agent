"""Vocabulary-size estimate from yes/no answers (ADR 0010 §4, P1 plan §6.1).

The learner says whether they know each word shown. Real words are drawn from bands
of frequency rank; about a quarter of the questions are pseudo-words. Pure functions:
the placement graph (task 15) keeps the answers and picks the words.

Model. A learner with vocabulary parameter V knows a word of rank r with probability
`p_know = 1 / (1 + (r / V)^k)`, so V is the rank at which they know half the words.
Saying yes to a real word means knowing it, or guessing yes at the false-alarm rate f
measured on pseudo-words: `p_yes = p_know + (1 - p_know) * f`. This is the classic
yes/no correction `(hits - f) / (1 - f)` built into the likelihood rather than applied
to band averages, so it also works when each band has only a few answers.

V is the maximum a posteriori fit over all real-word answers under a weak log-normal
prior (so all-yes or all-no still gives a finite V); the next question goes to the band
nearest the current fit, where an answer is most informative. The estimate is the
expected number of known words among the first `max_rank`, counting in each band the
words that can be tested (lemmas, not inflections or names; `placement.words`) rather
than every rank.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from app.adaptive.rules import PlacementVocabRules

# ln V is searched over 10 to 100,000 words: a coarse grid, then a fine grid around
# the best coarse point (steps of about 0.3%).
_LOG_V_MIN, _LOG_V_MAX, _GRID = math.log(10), math.log(100_000), 60


@dataclass(frozen=True, slots=True)
class Band:
    index: int
    first: int  # first rank in the band (1-based, inclusive)
    last: int  # last rank (inclusive)

    @property
    def middle(self) -> float:
        return (self.first + self.last) / 2


@dataclass(frozen=True, slots=True)
class Answer:
    """One answer: `rank` is the real word's frequency rank, None for a pseudo-word."""

    rank: int | None
    yes: bool


@dataclass(frozen=True, slots=True)
class VocabEstimate:
    size: int
    # The fitted V: rank at which the learner knows half the words.
    half_known_rank: int
    false_alarm: float
    reliable: bool


def bands(rules: PlacementVocabRules) -> list[Band]:
    size = rules.band_size
    return [Band(i, i * size + 1, (i + 1) * size) for i in range(rules.max_rank // size)]


def band_of(rank: int, rules: PlacementVocabRules) -> int | None:
    """Index of the band holding `rank`, or None past max_rank."""
    return (rank - 1) // rules.band_size if 1 <= rank <= rules.max_rank else None


def p_know(v: float, rank: float, rules: PlacementVocabRules) -> float:
    return 1 / (1 + math.pow(rank / v, rules.steepness))


def false_alarm_rate(answers: Sequence[Answer]) -> float:
    """Share of pseudo-words answered yes, smoothed so a handful of answers is not 0 or 1."""
    pseudo = [a.yes for a in answers if a.rank is None]
    return (sum(pseudo) + 0.5) / (len(pseudo) + 2)


def _log_posterior(
    log_v: float, real: Sequence[tuple[int, bool]], f: float, r: PlacementVocabRules
) -> float:
    total = -((log_v - math.log(r.prior_median)) ** 2) / (2 * r.prior_log_sd**2)
    v = math.exp(log_v)
    for rank, yes in real:
        k = p_know(v, rank, r)
        p_yes = k + (1 - k) * f
        total += math.log(p_yes if yes else 1 - p_yes)
    return total


def fit(answers: Sequence[Answer], rules: PlacementVocabRules) -> float:
    """The most probable V given the answers (the prior median when there are none)."""
    real = [(a.rank, a.yes) for a in answers if a.rank is not None]
    f = false_alarm_rate(answers)
    low, high = _LOG_V_MIN, _LOG_V_MAX
    for _ in range(2):
        step = (high - low) / _GRID
        best = max(
            (low + i * step for i in range(_GRID + 1)),
            key=lambda log_v: _log_posterior(log_v, real, f, rules),
        )
        low, high = max(_LOG_V_MIN, best - step), min(_LOG_V_MAX, best + step)
    return math.exp(best)


def expected_size(
    v: float, rules: PlacementVocabRules, band_words: Sequence[int] | None = None
) -> int:
    """Expected number of known words among the first max_rank, band by band.

    `band_words` is how many words each band counts; every rank when not given.
    """
    counts = band_words if band_words is not None else [rules.band_size] * len(bands(rules))
    total = sum(n * p_know(v, b.middle, rules) for b, n in zip(bands(rules), counts, strict=True))
    return round(total)


def rank_at(v: float, p: float, rules: PlacementVocabRules) -> int:
    """The rank up to which the learner knows each word with probability at least p."""
    return int(v * math.pow((1 - p) / p, 1 / rules.steepness))


def estimate(
    answers: Sequence[Answer],
    rules: PlacementVocabRules,
    band_words: Sequence[int] | None = None,
) -> VocabEstimate:
    v = fit(answers, rules)
    f = false_alarm_rate(answers)
    return VocabEstimate(
        size=expected_size(v, rules, band_words),
        half_known_rank=round(v),
        false_alarm=f,
        reliable=f < rules.unreliable_false_alarm,
    )


def schedule(rules: PlacementVocabRules, rng: random.Random) -> list[bool]:
    """Which questions are pseudo-words (True), in order; a fixed count, shuffled."""
    pseudo = round(rules.questions * rules.pseudo_share)
    order = [True] * pseudo + [False] * (rules.questions - pseudo)
    rng.shuffle(order)
    return order


def bands_by_distance(answers: Sequence[Answer], rules: PlacementVocabRules) -> list[Band]:
    """All bands, nearest the current fit first (log scale): the next question comes
    from the first one that still has an unused word."""
    log_v = math.log(fit(answers, rules))
    return sorted(bands(rules), key=lambda b: (abs(math.log(b.middle) - log_v), b.index))


def next_band(answers: Sequence[Answer], rules: PlacementVocabRules) -> Band:
    """The band whose middle is nearest the current fit, on a log scale."""
    return bands_by_distance(answers, rules)[0]
