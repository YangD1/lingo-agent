"""The grammar course (ADR 0044 §2): lesson order and lesson states."""

from datetime import UTC, datetime, timedelta

from app.adaptive.course import KCProgress, build, order
from app.adaptive.kc.catalog import GrammarCatalog, GrammarKC, get_grammar_catalog
from app.adaptive.rules import get_rules

RULES = get_rules()
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def kc(kc_id: str, cefr: str, *prerequisites: str) -> GrammarKC:
    return GrammarKC.model_validate(
        {
            "id": kc_id,
            "name_en": kc_id,
            "name_zh": kc_id,
            "cefr": cefr,
            "description": "A rule.",
            "prerequisites": prerequisites,
        }
    )


# Listed out of order on purpose: c needs b, which comes later in the file.
CATALOG = GrammarCatalog(
    kcs=(
        kc("g.a", "A1"),
        kc("g.c", "A1", "g.b"),
        kc("g.b", "A1", "g.a"),
        kc("g.d", "A1"),
        kc("g.e", "A2", "g.c"),
    )
)


def states(course_kcs: dict[str, KCProgress], level: str | None = None) -> dict[str, str]:
    course = build(CATALOG, course_kcs, level=level, now=NOW, rules=RULES)  # type: ignore[arg-type]
    return {lesson.kc.id: lesson.state for lesson in course.lessons}


def test_order_is_by_level_then_prerequisites_then_the_file() -> None:
    assert [k.id for k in order(CATALOG)] == ["g.a", "g.b", "g.c", "g.d", "g.e"]


def test_the_real_catalog_puts_every_prerequisite_first() -> None:
    catalog = get_grammar_catalog()
    seen: set[str] = set()
    for k in order(catalog):
        assert set(k.prerequisites) <= seen, k.id
        seen.add(k.id)
    assert len(seen) == len(catalog.kcs)


def test_a_new_learner_starts_at_the_first_lesson_and_the_rest_wait_for_prerequisites() -> None:
    course = build(CATALOG, {}, level=None, now=NOW, rules=RULES)
    assert course.current == "g.a"
    assert [(lesson.number, lesson.state) for lesson in course.lessons] == [
        (1, "available"),
        (2, "locked"),
        (3, "locked"),
        (4, "available"),
        (5, "locked"),
    ]
    assert course.lessons[1].blocked_by == ("g.a",)


def test_a_pass_needs_both_the_quiz_score_and_mastery() -> None:
    passed = KCProgress(0.85, started=True, quiz_score=0.8)
    low_score = KCProgress(0.99, started=True, quiz_score=0.6)
    low_p = KCProgress(0.7, started=True, quiz_score=1.0)
    assert states({"g.a": passed})["g.a"] == "passed"
    assert states({"g.a": passed})["g.b"] == "available"
    assert states({"g.a": low_score})["g.a"] == "learning"
    assert states({"g.a": low_p})["g.a"] == "learning"
    assert states({"g.a": low_p})["g.b"] == "locked"


def test_a_learned_kc_is_passed_and_comes_back_for_review_when_due() -> None:
    later = KCProgress(0.97, learned=True, due=NOW + timedelta(days=3))
    due = KCProgress(0.97, learned=True, due=NOW - timedelta(hours=1))
    slipped = KCProgress(0.3, started=True, quiz_score=1.0)
    assert states({"g.a": later})["g.a"] == "passed"
    assert states({"g.a": due})["g.a"] == "review"
    # Passed on the quiz once, then weak again: not passed any more.
    assert states({"g.a": slipped})["g.a"] == "learning"


def test_below_the_learners_level_only_weak_gaps_come_first() -> None:
    # A2 learner: A1 lessons are one level below (prior 0.7): not passed, but they do
    # not lock the A2 lesson and the course starts at the learner's level.
    course = build(CATALOG, {}, level="A2", now=NOW, rules=RULES)
    by_id = {lesson.kc.id: lesson for lesson in course.lessons}
    assert by_id["g.a"].state == "available"
    assert by_id["g.e"].state == "available"
    assert course.current == "g.e"
    # Placement showed a gap: that lesson comes first.
    weak = build(CATALOG, {"g.d": KCProgress(0.2)}, level="A2", now=NOW, rules=RULES)
    assert weak.current == "g.d"
    # Known well enough two levels down: passed without a quiz.
    b1 = build(CATALOG, {}, level="B1", now=NOW, rules=RULES)
    assert {lesson.state for lesson in b1.lessons if lesson.kc.cefr == "A1"} == {"passed"}


def test_next_after_skips_passed_lessons() -> None:
    course = build(
        CATALOG,
        {"g.b": KCProgress(0.9, quiz_score=1.0), "g.a": KCProgress(0.9, quiz_score=1.0)},
        level=None,
        now=NOW,
        rules=RULES,
    )
    after = course.next_after("g.a")
    assert after is not None and after.kc.id == "g.c"
    assert course.next_after("g.unknown") is None
