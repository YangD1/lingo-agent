from datetime import UTC, datetime, timedelta

import fsrs
import pytest

from app.adaptive.bkt import Observation
from app.adaptive.exercise.formats import SPECS
from app.adaptive.learned import Learned, progress
from app.adaptive.rules import Severity, get_rules

RULES = get_rules()
T0 = datetime(2026, 10, 1, 9, tzinfo=UTC)
# High enough that a few correct answers cross bkt.mastered; the gate is what we test.
P_HIGH = 0.9


def ex(
    fmt: str,
    hours: float,
    *,
    correct: bool = True,
    group: str | None = "s1",
    production: bool = True,
) -> Observation:
    kinds = SPECS[fmt].evidence  # type: ignore[index]
    return Observation(
        correct=correct,
        evidence=kinds[-1] if production else kinds[0],
        at=T0 + timedelta(hours=hours),
        source="exercise",
        format=fmt,
        group=group,
        # Stored like a wrong placement answer (wrong_choice, medium), so BKT counts it.
        severity=None if correct else "medium",
    )


def chat_mistake(hours: float, severity: Severity = "medium", source: str = "chat") -> Observation:
    return Observation(
        correct=False,
        evidence="production",
        at=T0 + timedelta(hours=hours),
        turn=f"m{hours}",
        severity=severity,
        source=source,
    )


def three_formats(start: float = 0.0, span: float = 21.0) -> list[Observation]:
    return [
        ex("choice4", start, group="a"),
        ex("cloze", start + 0.1, group="a"),
        ex("transform", start + span, group="b"),
    ]


def run(observations: list[Observation], p_init: float = P_HIGH) -> Learned:
    return progress(observations, p_init, RULES)


def test_learned_when_every_condition_holds() -> None:
    result = run(three_formats())
    assert result.formats_passed == ("choice4", "cloze", "transform")
    assert result.correct_span_hours == 21.0
    assert result.mastered_at == T0 + timedelta(hours=21)
    # The first review puts the card straight into review, about a week out.
    assert result.card is not None and result.card.state == fsrs.State.Review
    assert result.card.due - result.mastered_at >= timedelta(days=3)


def test_a_miss_in_the_set_that_completes_the_gate_starts_with_learning_steps() -> None:
    result = run([*three_formats(), ex("cloze", 21.1, correct=False, group="b")])
    assert result.mastered_at is not None
    assert result.card is not None and result.card.state == fsrs.State.Learning


def test_not_learned_with_too_few_formats() -> None:
    result = run([ex("choice4", 0), ex("choice4", 30), ex("cloze", 31)])
    assert result.formats_passed == ("choice4", "cloze")
    assert result.mastered_at is None and result.card is None


def test_not_learned_within_one_sitting() -> None:
    assert run(three_formats(span=5)).mastered_at is None
    # A later correct answer stretches the span past the threshold.
    later = run([*three_formats(span=5), ex("choice4", 25, group="c")])
    assert later.mastered_at == T0 + timedelta(hours=25)


def test_not_learned_while_low_p_mastery() -> None:
    # From near zero, three correct answers leave p_mastery just under bkt.mastered.
    assert run(three_formats(), p_init=0.001).mastered_at is None


def test_recent_free_mistake_blocks_learning() -> None:
    days = RULES.mastery_gate.clean_days
    recent = run([chat_mistake(-24 * (days - 1)), *three_formats()])
    assert recent.mastered_at is None
    assert recent.last_mistake_at == T0 - timedelta(days=days - 1)
    old = run([chat_mistake(-24 * (days + 1)), *three_formats()])
    assert old.mastered_at is not None


def test_uncounted_mistakes_do_not_block() -> None:
    result = run([chat_mistake(-1, severity="low"), *three_formats()])
    assert result.last_mistake_at is None
    assert result.mastered_at is not None


def test_practice_mistakes_are_not_free_use_mistakes() -> None:
    result = run([ex("choice4", -1, correct=False, group="z"), *three_formats()])
    assert result.last_mistake_at is None


def test_find_fix_passes_only_with_the_fix() -> None:
    spotted = run([ex("find_fix", 0, production=False)])
    assert spotted.formats_passed == ()
    fixed = run([ex("find_fix", 0, production=False), ex("find_fix", 0.01)])
    assert fixed.formats_passed == ("find_fix",)


def test_placement_answers_pass_no_format() -> None:
    placement = Observation(correct=True, evidence="recognition", at=T0, source="placement")
    assert run([placement]).formats_passed == ()


def test_one_review_per_practice_set() -> None:
    base = three_formats()
    once = run([*base, ex("choice4", 72, group="d")])
    thrice = run(
        [
            *base,
            ex("choice4", 72, group="d"),
            ex("cloze", 72.1, group="d"),
            ex("translate", 72.2, group="d"),
        ]
    )
    assert once.card is not None and thrice.card is not None
    assert thrice.card.stability == once.card.stability
    assert thrice.card.last_review == T0 + timedelta(hours=72.2)


def test_a_wrong_answer_in_a_set_is_again() -> None:
    base = three_formats()
    good = run([*base, ex("choice4", 72, group="d"), ex("cloze", 72.1, group="d")])
    again = run([*base, ex("choice4", 72, group="d"), ex("cloze", 72.1, correct=False, group="d")])
    assert good.card is not None and again.card is not None
    assert again.mastered_at is not None  # one miss does not revoke
    assert again.card.state == fsrs.State.Relearning
    assert again.card.due < good.card.due


def test_free_mistake_after_learning_is_again() -> None:
    result = run([*three_formats(), chat_mistake(100)])
    assert result.mastered_at is not None
    assert result.card is not None and result.card.state == fsrs.State.Relearning
    assert result.last_mistake_at == T0 + timedelta(hours=100)


@pytest.mark.parametrize("source", ["writing", "speaking"])
def test_writing_and_speaking_mistakes_count_like_chat(source: str) -> None:
    result = run([*three_formats(), chat_mistake(100, source=source)])
    assert result.card is not None and result.card.state == fsrs.State.Relearning


def test_falling_below_weak_revokes_and_restarts_progress() -> None:
    misses = [chat_mistake(100 + i) for i in range(6)]
    revoked = run([*three_formats(), *misses])
    assert revoked.mastered_at is None and revoked.card is None
    assert revoked.formats_passed == ()
    # Progress counts again from scratch afterwards.
    again = run([*three_formats(), *misses, ex("cloze", 110, group="e")])
    assert again.formats_passed == ("cloze",)


def test_replay_is_deterministic() -> None:
    observations = [*three_formats(), ex("choice4", 72, group="d"), chat_mistake(200)]
    first, second = run(observations), run(list(reversed(observations)))
    assert first.card is not None and second.card is not None
    assert first.card.to_dict() == second.card.to_dict()
    assert first == second
