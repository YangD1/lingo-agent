"""A simulated learner with known weak points, practising day after day (ADR 0033 §5).

The learner is a rule, not a model: on each grammar KC it answers correctly with a
fixed chance, low on its weak KCs (rising as it practises them, so it learns) and
high elsewhere. The engine is the app's own pure functions: `bkt.replay` and
`learned.progress` over the evidence, `planner.plan` for each set, `elo` for ability.
The glue that loads these from the database (`exercise.inputs.load`) is mirrored in
`_states`; the database round trip itself is covered by the integration tests.

`python -m evals.simulated_learner` prints the run day by day.
"""

import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.adaptive.bkt import Observation, prior, replay
from app.adaptive.elo import guess_for, update_ability
from app.adaptive.exercise.formats import SPECS
from app.adaptive.exercise.planner import KCState, PlannedItem, plan
from app.adaptive.kc.catalog import CefrLevel, GrammarCatalog, get_grammar_catalog
from app.adaptive.learned import progress
from app.adaptive.rules import Rules, get_rules

START = datetime(2026, 1, 5, 9, tzinfo=UTC)

# Weak points: present perfect in its common B1 uses, and the first conditional.
WEAK = ("g.present_perfect_vs_past_simple", "g.present_perfect_for_since", "g.first_conditional")
# One-off slips in conversation on KCs the learner actually knows.
SLIPS = ("g.comparatives", "g.used_to")


@dataclass(frozen=True, slots=True)
class Learner:
    level: CefrLevel = "B1"
    # Chance of a correct answer on a weak KC before any practice, and how much each
    # practised item adds, up to `ceiling`.
    weak_start: float = 0.25
    gain: float = 0.06
    ceiling: float = 0.95
    # Everywhere else.
    known: float = 0.93
    weak: tuple[str, ...] = WEAK
    slips: tuple[str, ...] = SLIPS

    def p_correct(self, kc_id: str, practised: int) -> float:
        if kc_id in self.weak:
            return min(self.weak_start + self.gain * practised, self.ceiling)
        return self.known


@dataclass(frozen=True, slots=True)
class Day:
    day: int
    # What the set was planned from.
    before: Mapping[str, KCState]
    items: Sequence[PlannedItem]
    correct: Sequence[bool]
    # p_mastery after the day's set, of the KCs with evidence.
    mastery: Mapping[str, float]
    learned: frozenset[str]


@dataclass
class Run:
    learner: Learner
    days: list[Day] = field(default_factory=list)

    def share_on(self, kcs: Sequence[str], days: range) -> float:
        items = [i for d in self.days if d.day in days for i in d.items]
        return sum(i.kc_id in kcs for i in items) / len(items) if items else 0.0


def _states(
    history: Mapping[str, list[Observation]],
    catalog: GrammarCatalog,
    level: CefrLevel,
    rules: Rules,
    now: datetime,
) -> dict[str, KCState]:
    """What `inputs.load` reads from kc_mastery and kc_evidence."""
    since = now - timedelta(days=rules.practice.recent_mistake_days)
    out = {}
    for kc_id, observations in history.items():
        kc = catalog.get(kc_id)
        assert kc is not None
        p_init = prior(kc.cefr, level, rules)
        learned = progress(observations, p_init, rules)
        out[kc_id] = KCState(
            p_mastery=replay(observations, p_init, rules).p_mastery,
            formats_passed=frozenset(learned.formats_passed),
            recent_mistakes=sum(
                not o.correct
                and o.severity in rules.evidence.counted_severities
                and o.source != "placement"
                and o.at >= since
                for o in observations
            ),
            learned=learned.mastered_at is not None,
            due=learned.card.due if learned.card else None,
            gate_ready_at=learned.gate_ready_at,
        )
    return out


def simulate(learner: Learner | None = None, days: int = 30, seed: int = 7) -> Run:
    """One practice set a day for `days` days, after two chat mistakes on each weak KC
    and one on each slip on day 0."""
    learner = learner or Learner()
    rules, catalog = get_rules(), get_grammar_catalog()
    rng = random.Random(seed)
    history: dict[str, list[Observation]] = {}
    for n, kc_id in enumerate([*learner.weak, *learner.weak, *learner.slips]):
        at = START - timedelta(hours=2) + timedelta(minutes=n)
        history.setdefault(kc_id, []).append(
            Observation(False, "production", at, turn=f"chat:{n}", severity="medium")
        )
    ability = rules.difficulty.cefr_anchor[learner.level]
    answers = 0
    practised: Counter[str] = Counter()
    run = Run(learner)
    for day in range(days):
        now = START + timedelta(days=day)
        states = _states(history, catalog, learner.level, rules, now)
        items = plan(
            catalog,
            states,
            learner_level=learner.level,
            ability=ability,
            now=now,
            rules=rules,
            seed=seed * 1000 + day,
        )
        correct = []
        for n, item in enumerate(items):
            right = rng.random() < learner.p_correct(item.kc_id, practised[item.kc_id])
            practised[item.kc_id] += 1
            at = now + timedelta(minutes=n)
            for evidence in SPECS[item.format].evidence:
                history.setdefault(item.kc_id, []).append(
                    Observation(
                        right,
                        evidence,
                        at,
                        severity=None if right else "medium",
                        source="exercise",
                        format=item.format,
                        group=f"set:{day}",
                    )
                )
            guess = guess_for(item.format, rules)
            ability = update_ability(ability, item.target_difficulty, right, answers, rules, guess)
            answers += 1
            correct.append(right)
        after = _states(history, catalog, learner.level, rules, now + timedelta(hours=1))
        run.days.append(
            Day(
                day,
                states,
                items,
                correct,
                {k: s.p_mastery for k, s in after.items()},
                frozenset(k for k, s in after.items() if s.learned),
            )
        )
    return run


def main() -> None:
    run = simulate()
    watched = [*run.learner.weak, *run.learner.slips]
    print("day  weak-items  " + "  ".join(k.removeprefix("g.")[:14].ljust(14) for k in watched))
    for d in run.days:
        on_weak = sum(i.kc_id in run.learner.weak for i in d.items)
        cells = []
        for k in watched:
            mark = "*" if k in d.learned else " "
            cells.append(f"{d.mastery.get(k, 0):.2f}{mark}".ljust(14))
        print(f"{d.day:>3}  {on_weak:>2}/{len(d.items):<2}       " + "  ".join(cells))
    print("* learned (mastery gate passed)")


if __name__ == "__main__":
    main()
