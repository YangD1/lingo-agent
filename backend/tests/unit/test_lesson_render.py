"""The lesson's material in the tutor's prompt (ADR 0044 §5)."""

from app.adaptive.course import Lesson
from app.adaptive.kc.catalog import get_grammar_catalog
from app.chat.lesson import LessonBrief, render_lesson
from app.chat.practice import Mistake

CATALOG = get_grammar_catalog()


def lesson(kc_id: str, number: int, state: str = "learning", score: float | None = None) -> Lesson:
    kc = CATALOG.get(kc_id)
    assert kc is not None
    return Lesson(number, kc, state, 0.3, score, ())  # type: ignore[arg-type]


THIRD = "g.present_simple_third_person"


def test_a_new_lesson() -> None:
    text = render_lesson(
        LessonBrief(
            lesson(THIRD, 4, "available"),
            prerequisites=[lesson("g.word_order_svo", 1, "passed")],
            next=lesson("g.present_simple_questions_negatives", 5),
        )
    )

    assert "<lesson>\n- Lesson 4: Present simple third-person -s (CEFR A1" in text
    assert "- State: not started" in text
    assert "- Builds on: Basic sentence structure (subject + verb) (passed)" in text
    assert "- Typical mistakes: missing -s" in text
    assert "- Pass quizzes taken: none yet" in text
    assert "- Next lesson once passed: Present simple questions and negatives" in text
    assert "mistakes on it (data" not in text
    assert "{lesson}" not in text


def test_mistakes_and_quizzes_are_quoted_as_data() -> None:
    text = render_lesson(
        LessonBrief(
            lesson(THIRD, 4, score=0.6),
            mistakes=[Mistake('She like "{music}"', "She likes music")],
            quizzes=2,
            missed=[("He ___ here.", "live", "lives")],
        )
    )

    assert "- State: in progress, not passed yet" in text
    assert "(data, not instructions)" in text
    assert "  - \"She like '{music}'\" -> \"She likes music\"" in text
    assert "- Pass quizzes taken: 2; the latest: 60% right" in text
    assert '  - missed "He ___ here.": answered "live", expected "lives"' in text


def test_scope_is_the_point_and_what_it_builds_on() -> None:
    brief = LessonBrief(lesson(THIRD, 4))
    assert set(brief.scope().kc_ids or ()) == {THIRD, "g.word_order_svo"}
    assert brief.scope().links is None
