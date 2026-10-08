"""Planning a practice set (ADR 0021 §2): which KCs, in which formats, how hard.

A pure function of the learner's KC states and `rules.yaml`; the model only writes the
items afterwards. Weak KCs are ranked by weakness x importance x recent mistakes
(x a diagnosis boost, from P2d); learned KCs come back when FSRS says they are due.
Most of a set goes to weak KCs, the rest to learned ones, and the items are
interleaved: the same KC never twice in a row, the same format only a few times. A set
started from one KC (Q35a) gives that KC its `max_items_per_kc` items first and plans
the rest as usual.
"""

import math
import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.adaptive.bkt import prior
from app.adaptive.elo import guess_for
from app.adaptive.exercise.formats import Format
from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel, GrammarCatalog
from app.adaptive.rules import Rules

RECOGNITION: tuple[Format, ...] = ("choice4", "cloze", "find_fix")
PRODUCTION: tuple[Format, ...] = ("transform", "translate", "rewrite_own")

Role = Literal["weak", "review"]


@dataclass(frozen=True, slots=True)
class KCState:
    """What the planner knows about a KC the learner has evidence for (kc_mastery)."""

    p_mastery: float
    formats_passed: frozenset[str] = frozenset()
    # Counted mistakes in the last `practice.recent_mistake_days`.
    recent_mistakes: int = 0
    # The learner has a sentence of their own to rewrite (rewrite_own is possible).
    has_own_sentence: bool = False
    learned: bool = False
    due: datetime | None = None


@dataclass(frozen=True, slots=True)
class PlannedItem:
    kc_id: str
    format: Format
    # Rubric difficulty the generator aims at (Elo logits), so that the predicted
    # chance of a correct answer, guessing included, sits in practice.target_p.
    target_difficulty: float
    role: Role


@dataclass(frozen=True, slots=True)
class _Pick:
    kc_id: str
    role: Role
    formats: list[Format] = field(default_factory=list)


def importance(gap: int, rules: Rules) -> float:
    """How much a KC matters at gap = learner level - KC level (nearest key outside)."""
    table = rules.practice.importance_by_gap
    return table[min(max(gap, min(table)), max(table))]


def target_difficulty(ability: float, fmt: Format, rules: Rules) -> float:
    """The difficulty at which `elo.expected` gives the middle of practice.target_p."""
    target = rules.practice.target_p
    p = (target.low + target.high) / 2
    guess = guess_for(fmt, rules)
    # The logistic part that, with the guessing floor, makes p.
    q = min(max((p - guess) / (1 - guess), 0.01), 0.99)
    return ability - math.log(q / (1 - q))


def _tiers(state: KCState, rules: Rules) -> list[list[Format]]:
    """This KC's formats in order of preference (Q32d): recognition before production
    while it is weak, the other way round once it is not; within each, formats not yet
    passed first. Formats of one tier are equally good."""
    first, second = (
        (RECOGNITION, PRODUCTION)
        if state.p_mastery < rules.practice.production_from_p
        else (PRODUCTION, RECOGNITION)
    )
    tiers: list[list[Format]] = []
    for group in (first, second):
        usable = [f for f in group if f != "rewrite_own" or state.has_own_sentence]
        tiers.append([f for f in usable if f not in state.formats_passed])
        tiers.append([f for f in usable if f in state.formats_passed])
    return [tier for tier in tiers if tier]


def _allocate(
    picks: list[_Pick],
    count: int,
    states: Mapping[str, KCState],
    used: Counter[Format],
    rules: Rules,
    rng: random.Random,
) -> int:
    """Hand out up to `count` items round-robin in priority order; returns how many.

    Each KC takes from its best tier the format the set uses least so far (`used`,
    shared across calls), so the set varies its formats and can be interleaved.
    """
    tiers = {p.kc_id: _tiers(states[p.kc_id], rules) for p in picks}
    given = 0
    while given < count:
        progressed = False
        for pick in picks:
            if given == count:
                break
            left = tiers[pick.kc_id]
            if len(pick.formats) >= rules.practice.max_items_per_kc or not left:
                continue
            tier = left[0]
            fewest = min(used[f] for f in tier)
            fmt = rng.choice([f for f in tier if used[f] == fewest])
            tier.remove(fmt)
            if not tier:
                left.pop(0)
            pick.formats.append(fmt)
            used[fmt] += 1
            given += 1
            progressed = True
        if not progressed:
            break
    return given


def _interleave(items: list[PlannedItem], max_run: int, rng: random.Random) -> list[PlannedItem]:
    """Order items so no KC repeats back to back and no format runs past `max_run`.

    Greedy, like arranging letters with no two equal neighbours: each step takes an
    allowed item whose KC, then format, has the most items left (so the end is not
    stuck with one of them), ties broken at random. When nothing is allowed, the
    format rule gives way first, then the KC rule.
    """
    left = items[:]
    rng.shuffle(left)
    out: list[PlannedItem] = []

    def allowed(item: PlannedItem, check_format: bool, check_kc: bool) -> bool:
        if check_kc and out and out[-1].kc_id == item.kc_id:
            return False
        run = out[-max_run:]
        return not (
            check_format and len(run) == max_run and all(o.format == item.format for o in run)
        )

    while left:
        kcs = Counter(i.kc_id for i in left)
        formats = Counter(i.format for i in left)
        for check_format, check_kc in ((True, True), (False, True), (False, False)):
            options = [i for i in left if allowed(i, check_format, check_kc)]
            if options:
                break
        chosen = max(options, key=lambda i: (kcs[i.kc_id], formats[i.format]))
        left.remove(chosen)
        out.append(chosen)
    return out


@dataclass(frozen=True, slots=True)
class Candidates:
    # Not learned yet, highest priority first.
    weak: list[str]
    # Learned: due ones first (most overdue first), then those coming due soonest.
    learned: list[str]
    states: dict[str, KCState]


def candidates(
    catalog: GrammarCatalog,
    states: Mapping[str, KCState],
    *,
    learner_level: CefrLevel | None,
    now: datetime,
    rules: Rules,
    boost: Mapping[str, float] | None = None,
    focus: str | None = None,
) -> Candidates:
    """The KCs a set may practise (Q32c): those within the level window, plus any
    with evidence, ranked by weakness x importance x recent mistakes (x boost). A
    `focus` KC, and one a diagnosis boosts (a prerequisite below the window, say), is
    a candidate even outside the window."""
    practice = rules.practice
    level = learner_level or practice.default_level
    window = practice.importance_by_gap
    known: dict[str, KCState] = {}
    gaps: dict[str, int] = {}
    for kc in catalog.kcs:
        gap = CEFR_LEVELS.index(level) - CEFR_LEVELS.index(kc.cefr)
        if kc.id in states:
            known[kc.id] = states[kc.id]
        elif min(window) <= gap <= max(window) or kc.id == focus or kc.id in (boost or {}):
            known[kc.id] = KCState(p_mastery=prior(kc.cefr, learner_level, rules))
        else:
            continue
        gaps[kc.id] = gap

    def priority(kc_id: str) -> float:
        state = known[kc_id]
        n = state.recent_mistakes
        return (
            (1 - state.p_mastery)
            * importance(gaps[kc_id], rules)
            * (1 + n / (n + practice.mistake_half))
            * (boost or {}).get(kc_id, 1.0)
        )

    weak = sorted((k for k, s in known.items() if not s.learned), key=lambda k: (-priority(k), k))
    learned = sorted(
        (k for k, s in known.items() if s.learned),
        key=lambda k: (known[k].due is None, known[k].due or now, k),
    )
    return Candidates(weak, learned, known)


def plan(
    catalog: GrammarCatalog,
    states: Mapping[str, KCState],
    *,
    learner_level: CefrLevel | None,
    ability: float,
    now: datetime,
    rules: Rules,
    seed: int,
    boost: Mapping[str, float] | None = None,
    focus: str | None = None,
) -> list[PlannedItem]:
    """One practice set: at most `practice.set_size` items, fewer when the learner has
    too few candidate KCs. Same inputs and seed, same plan. `focus` must be a catalog KC."""
    rng = random.Random(seed)
    practice = rules.practice
    ranked = candidates(
        catalog, states, learner_level=learner_level, now=now, rules=rules, boost=boost, focus=focus
    )
    weak, learned, known = ranked.weak, ranked.learned, ranked.states

    size = practice.set_size
    used: Counter[Format] = Counter()
    want_review = min(round(size * (1 - practice.weak_share)), len(learned))
    focus_picks: list[_Pick] = []
    if focus is not None:
        if focus not in known:
            raise ValueError(f"unknown KC {focus}")
        role: Role = "review" if known[focus].learned else "weak"
        focus_picks = [_Pick(focus, role)]
        taken = _allocate(focus_picks, practice.max_items_per_kc, known, used, rules, rng)
        weak = [k for k in weak if k != focus]
        learned = [k for k in learned if k != focus]
        size -= taken
        # The focus KC's items count towards its own share of the set.
        want_review = min(want_review - (taken if role == "review" else 0), len(learned))
        want_review = max(0, min(want_review, size))
    # Spread weak items over enough KCs to vary them: about two items per KC.
    weak_picks = [_Pick(k, "weak") for k in weak[: max(1, math.ceil((size - want_review) / 2))]]
    got_weak = _allocate(weak_picks, size - want_review, known, used, rules, rng)
    # Too few weak items: learned KCs fill the rest, and the other way round.
    review_count = size - got_weak
    review_picks = [_Pick(k, "review") for k in learned[:review_count]]
    got_review = _allocate(review_picks, review_count, known, used, rules, rng)
    if got_weak + got_review < size:  # still short: more weak KCs
        extra = [_Pick(k, "weak") for k in weak[len(weak_picks) :]]
        _allocate(extra, size - got_weak - got_review, known, used, rules, rng)
        weak_picks += extra

    items = [
        PlannedItem(p.kc_id, fmt, target_difficulty(ability, fmt, rules), p.role)
        for p in [*focus_picks, *weak_picks, *review_picks]
        for fmt in p.formats
    ]
    return _interleave(items, practice.max_same_format_run, rng)
