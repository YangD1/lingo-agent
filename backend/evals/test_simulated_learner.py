"""The adaptive engine finds and works on a simulated learner's weak points (ADR 0033 §5).

No model is called: the learner is a rule and the engine its pure functions."""

from datetime import timedelta

import pytest

from app.adaptive.rules import get_rules
from evals.simulated_learner import START, Learner, simulate

SEEDS = (1, 7, 42)


@pytest.mark.parametrize("seed", SEEDS)
def test_first_sets_go_to_the_weak_points(seed: int) -> None:
    run = simulate(days=3, seed=seed)
    weak = run.learner.weak

    assert {i.kc_id for i in run.days[0].items} >= set(weak)
    # Three of about a hundred candidate KCs; at random this would be 3 %.
    assert run.share_on(weak, range(3)) >= 0.4


@pytest.mark.parametrize("seed", SEEDS)
def test_a_shown_weakness_is_not_crowded_out_by_untested_kcs(seed: int) -> None:
    """Q68d: a KC with recent mistakes, not learned and below 0.8, is in every set."""
    run = simulate(days=30, seed=seed)
    for day in run.days:
        planned = {i.kc_id for i in day.items}
        for kc_id, state in day.before.items():
            if state.recent_mistakes and not state.learned and state.p_mastery < 0.8:
                assert kc_id in planned, (day.day, kc_id, state)


@pytest.mark.parametrize("seed", SEEDS)
def test_consolidating_kcs_come_back_until_learned(seed: int) -> None:
    """Q68e: a KC mastered by p_mastery but short of the gate is not left out: once an
    answer could pass the gate it waits in the review queue, and in the end passes."""
    rules = get_rules()
    run = simulate(days=45, seed=seed)
    waiting: dict[str, int] = {}
    for day in run.days:
        now = START + timedelta(days=day.day)
        planned = {i.kc_id for i in day.items}
        for kc_id, state in day.before.items():
            ready = state.gate_ready_at
            if state.learned or ready is None or ready > now:
                waiting.pop(kc_id, None)
            elif kc_id in planned:
                waiting[kc_id] = 0
            else:
                waiting[kc_id] = waiting.get(kc_id, 0) + 1
                # About seventy KCs queue for three review items a day.
                assert waiting[kc_id] <= 14, (day.day, kc_id)
    last = run.days[-1]
    for kc_id in (*run.learner.weak, *run.learner.slips):
        assert kc_id in last.learned, kc_id
        assert last.mastery[kc_id] >= rules.bkt.mastered
    # ...having started low: the chat mistakes put them there before any practice.
    for kc_id in run.learner.weak:
        assert run.days[0].before[kc_id].p_mastery < 0.3, kc_id


def test_a_weak_point_that_stays_weak_is_practised_every_day() -> None:
    stuck = Learner(gain=0.0, weak_start=0.2)
    run = simulate(stuck, days=14)
    low = [k for k in stuck.weak if run.days[-1].mastery[k] < 0.5]
    assert low
    for day in run.days:
        assert set(low) <= {i.kc_id for i in day.items}, day.day
    assert not set(low) & run.days[-1].learned
