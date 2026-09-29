import random

import pytest

from app.adaptive.placement.vocab_size import (
    Answer,
    band_of,
    bands,
    bands_by_distance,
    estimate,
    expected_size,
    false_alarm_rate,
    fit,
    next_band,
    p_know,
    rank_at,
    schedule,
)
from app.adaptive.rules import PlacementVocabRules


@pytest.fixture
def rules() -> PlacementVocabRules:
    """Fixed parameters, so these tests don't move when rules.yaml is tuned."""
    return PlacementVocabRules(
        band_size=1000,
        max_rank=20000,
        questions=40,
        pseudo_share=0.25,
        steepness=3.0,
        prior_median=3000,
        prior_log_sd=1.5,
        unreliable_false_alarm=0.4,
    )


def simulate(true_v: float, rules: PlacementVocabRules, seed: int, f: float = 0.0) -> list[Answer]:
    """A learner who knows words by the model and says yes to pseudo-words at rate f."""
    rng = random.Random(seed)
    answers: list[Answer] = []
    for is_pseudo in schedule(rules, rng):
        if is_pseudo:
            answers.append(Answer(None, rng.random() < f))
            continue
        band = next_band(answers, rules)
        rank = rng.randint(band.first, band.last)
        knows = rng.random() < p_know(true_v, rank, rules)
        answers.append(Answer(rank, knows or rng.random() < f))
    return answers


def test_bands(rules: PlacementVocabRules) -> None:
    all_bands = bands(rules)
    assert len(all_bands) == 20
    assert (all_bands[0].first, all_bands[0].last) == (1, 1000)
    assert (all_bands[-1].first, all_bands[-1].last) == (19001, 20000)
    assert [band_of(r, rules) for r in (1, 1000, 1001, 20000, 20001, 0)] == [
        0, 0, 1, 19, None, None,
    ]  # fmt: skip


def test_p_know_is_half_at_v(rules: PlacementVocabRules) -> None:
    assert p_know(5000, 5000, rules) == pytest.approx(0.5)
    assert p_know(5000, 1000, rules) > 0.9
    assert p_know(5000, 20000, rules) < 0.05


def test_expected_size_rises_with_v(rules: PlacementVocabRules) -> None:
    sizes = [expected_size(v, rules) for v in (100, 1000, 3000, 8000, 20000, 100000)]
    assert sizes == sorted(sizes)
    assert sizes[0] < 200
    assert sizes[-1] <= rules.max_rank


def test_no_answers_gives_prior(rules: PlacementVocabRules) -> None:
    assert fit([], rules) == pytest.approx(3000, rel=0.02)
    # On a log scale 3000 is nearer the middle of 3001-4000 than of 2001-3000.
    assert next_band([], rules).index == 3


def test_false_alarm_rate_is_smoothed() -> None:
    assert false_alarm_rate([]) == 0.25
    assert false_alarm_rate([Answer(None, False)] * 10) == pytest.approx(0.5 / 12)
    assert false_alarm_rate([Answer(None, True)] * 10) == pytest.approx(10.5 / 12)
    assert false_alarm_rate([Answer(5, True)] * 10) == 0.25  # real words don't count


def test_all_no_is_small_all_yes_is_large(rules: PlacementVocabRules) -> None:
    def run(yes: bool) -> int:
        answers: list[Answer] = [Answer(None, False)] * 10
        for _ in range(30):
            band = next_band(answers, rules)
            answers.append(Answer(band.first, yes))
        return estimate(answers, rules).size

    assert run(False) < 500
    assert run(True) > 15000


def test_false_alarms_lower_the_estimate(rules: PlacementVocabRules) -> None:
    real = [Answer(rank, rank <= 6000) for rank in range(500, 15000, 500)]
    sizes = [
        estimate(real + [Answer(None, i < n) for i in range(10)], rules).size for n in (0, 3, 6, 9)
    ]
    assert sizes == sorted(sizes, reverse=True)
    assert sizes[0] > sizes[-1]


def test_reliability_flag(rules: PlacementVocabRules) -> None:
    honest = estimate([Answer(None, False)] * 10, rules)
    guesser = estimate([Answer(None, True)] * 5 + [Answer(None, False)] * 5, rules)
    assert honest.reliable
    assert not guesser.reliable


def test_schedule(rules: PlacementVocabRules) -> None:
    order = schedule(rules, random.Random(1))
    assert len(order) == 40 and sum(order) == 10
    assert order == schedule(rules, random.Random(1))


@pytest.mark.parametrize("true_v", [800, 2500, 6000, 12000])
def test_recovers_simulated_learner(rules: PlacementVocabRules, true_v: int) -> None:
    """Over several simulated runs, the median fit is within a factor 1.5 of the truth."""
    fits = sorted(fit(simulate(true_v, rules, seed), rules) for seed in range(15))
    median = fits[len(fits) // 2]
    assert true_v / 1.5 < median < true_v * 1.5


def test_estimate_rises_with_ability(rules: PlacementVocabRules) -> None:
    def mean_size(true_v: int) -> float:
        runs = [estimate(simulate(true_v, rules, seed), rules).size for seed in range(10)]
        return sum(runs) / len(runs)

    means = [mean_size(v) for v in (800, 2500, 6000, 12000)]
    assert means == sorted(means)


def test_guessing_learner_is_corrected(rules: PlacementVocabRules) -> None:
    """Someone who also says yes to a third of unknown words is not credited for it."""
    honest = [estimate(simulate(3000, rules, s), rules).size for s in range(10)]
    guesser = [estimate(simulate(3000, rules, s, f=0.33), rules).size for s in range(10)]
    assert abs(sum(guesser) - sum(honest)) / sum(honest) < 0.3


def test_expected_size_counts_the_words_of_each_band(rules: PlacementVocabRules) -> None:
    every_rank = expected_size(5000, rules)
    assert expected_size(5000, rules, [1000] * 20) == every_rank
    assert expected_size(5000, rules, [800] * 20) == pytest.approx(every_rank * 0.8, abs=1)
    assert expected_size(5000, rules, [0] * 20) == 0
    with pytest.raises(ValueError):
        expected_size(5000, rules, [1000] * 3)


def test_rank_at(rules: PlacementVocabRules) -> None:
    assert rank_at(4000, 0.5, rules) == 4000
    at_90 = rank_at(4000, 0.9, rules)
    assert at_90 < 4000
    assert p_know(4000, at_90, rules) == pytest.approx(0.9, abs=0.001)


def test_bands_by_distance_start_at_next_band(rules: PlacementVocabRules) -> None:
    answers = [Answer(rank=500, yes=True), Answer(rank=9000, yes=False)]
    order = bands_by_distance(answers, rules)
    assert order[0] == next_band(answers, rules)
    assert sorted(b.index for b in order) == list(range(20))
