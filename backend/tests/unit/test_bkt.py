from datetime import UTC, datetime, timedelta

import pytest

from app.adaptive.bkt import Observation, counted, is_mastered, prior, replay, update
from app.adaptive.rules import BktRules, EvidenceRules, Rules, load_rules

T0 = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def rules() -> Rules:
    """Fixed parameters, so these tests don't move when rules.yaml is tuned."""
    base = load_rules()
    return base.model_copy(
        update={
            "bkt": BktRules(
                p_learn=0.1,
                p_slip=0.1,
                p_guess={"recognition": 0.2, "production": 0.05},
                mastered=0.95,
                prior_by_gap={2: 0.9, 1: 0.7, 0: 0.4, -1: 0.15},
                prior_unknown_learner={
                    "A1": 0.6,
                    "A2": 0.5,
                    "B1": 0.35,
                    "B2": 0.25,
                    "C1": 0.15,
                    "C2": 0.1,
                },
            ),
            "evidence": EvidenceRules(
                counted_severities=frozenset({"medium", "high"}), max_per_turn=1
            ),
        }
    )


def obs(minutes: int, correct: bool, **kw: object) -> Observation:
    return Observation(
        correct=correct,
        evidence=kw.pop("evidence", "production"),  # type: ignore[arg-type]
        at=T0 + timedelta(minutes=minutes),
        severity=kw.pop("severity", None if correct else "medium"),  # type: ignore[arg-type]
        turn=kw.pop("turn", None),  # type: ignore[arg-type]
    )


def test_update_matches_hand_computed_values(rules: Rules) -> None:
    # correct recognition: 0.36 / (0.36 + 0.6 * 0.2) = 0.75, then + 0.25 * 0.1
    assert update(0.4, True, "recognition", rules) == pytest.approx(0.775)
    # wrong: 0.04 / (0.04 + 0.6 * 0.8) = 1/13, then + (12/13) * 0.1
    assert update(0.4, False, "recognition", rules) == pytest.approx(1 / 13 + 1.2 / 13)
    # correct production: 0.36 / (0.36 + 0.6 * 0.05) = 12/13, then + (1/13) * 0.1
    assert update(0.4, True, "production", rules) == pytest.approx(12 / 13 + 0.1 / 13)


def test_production_is_stronger_evidence_than_recognition(rules: Rules) -> None:
    assert update(0.3, True, "production", rules) > update(0.3, True, "recognition", rules)


@pytest.mark.parametrize("p", [0.0, 0.01, 0.5, 0.99, 1.0])
@pytest.mark.parametrize("correct", [True, False])
@pytest.mark.parametrize("evidence", ["recognition", "production"])
def test_update_stays_a_probability(rules: Rules, p: float, correct: bool, evidence: str) -> None:
    assert 0.0 <= update(p, correct, evidence, rules) <= 1.0  # type: ignore[arg-type]


def test_repeated_success_converges_and_errors_lower(rules: Rules) -> None:
    p = 0.2
    for _ in range(30):
        p = update(p, True, "recognition", rules)
    assert p > 0.99 and is_mastered(p, rules)
    assert update(p, False, "recognition", rules) < p


def test_prior_by_gap_and_unknown_learner(rules: Rules) -> None:
    assert prior("A1", "B1", rules) == 0.9  # two levels below
    assert prior("A1", "C2", rules) == 0.9  # gap 5 clamps to the largest key
    assert prior("A2", "B1", rules) == 0.7
    assert prior("B1", "B1", rules) == 0.4
    assert prior("C2", "A1", rules) == 0.15  # gap -5 clamps to the smallest key
    assert prior("B2", None, rules) == 0.25


def test_low_severity_mistakes_are_not_counted(rules: Rules) -> None:
    history = [obs(0, False, severity="low"), obs(1, False, severity="high")]
    assert [o.severity for o in counted(history, rules)] == ["high"]
    result = replay(history, 0.5, rules)
    assert result.observations == 1
    assert result.last_evidence_at == T0 + timedelta(minutes=1)


def test_one_observation_per_turn_errors_first(rules: Rules) -> None:
    history = [
        obs(0, True, turn="m1"),
        obs(1, False, turn="m1"),
        obs(2, False, turn="m1"),
        obs(3, True, turn="m2"),
        obs(4, True, evidence="recognition"),  # placement answer, no turn
        obs(5, True, evidence="recognition"),
    ]
    kept = counted(history, rules)
    assert [(o.turn, o.correct) for o in kept] == [
        ("m1", False), ("m2", True), (None, True), (None, True)
    ]  # fmt: skip
    result = replay(history, 0.4, rules)
    assert (result.observations, result.recog_correct, result.produce_correct) == (4, 2, 1)


def test_replay_is_order_independent_of_input_and_applies_in_time_order(rules: Rules) -> None:
    history = [obs(0, False), obs(1, True), obs(2, True)]
    expected = update(update(update(0.4, False, "production", rules), True, "production", rules),
                      True, "production", rules)  # fmt: skip
    assert replay(reversed(history), 0.4, rules).p_mastery == pytest.approx(expected)


def test_rule_change_changes_replayed_mastery(rules: Rules) -> None:
    history = [obs(0, False, severity="low"), obs(1, False, severity="low")]
    strict = rules.model_copy(
        update={
            "evidence": EvidenceRules(
                counted_severities=frozenset({"low", "medium", "high"}), max_per_turn=1
            )
        }
    )
    assert replay(history, 0.5, rules).p_mastery == 0.5
    assert replay(history, 0.5, strict).p_mastery < 0.5


def test_empty_history(rules: Rules) -> None:
    result = replay([], 0.35, rules)
    assert result.p_mastery == 0.35 and result.observations == 0 and result.last_evidence_at is None
