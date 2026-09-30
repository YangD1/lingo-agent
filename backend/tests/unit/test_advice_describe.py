"""Candidates in plain English for the tutor's prompt (ADR 0016)."""

from app.adaptive.kc.catalog import get_grammar_catalog
from app.advice.candidates import Candidate, Example
from app.advice.describe import describe
from app.services.vocab.books import get_book

KC = get_grammar_catalog().get("g.present_simple_third_person")
assert KC is not None


def test_each_kind_with_its_evidence() -> None:
    assert describe(Candidate("placement", "placement", 1.0)) == (
        "Take the placement test: never taken"
    )
    retest = Candidate("placement", "placement", 0.4, days_since=70, in_progress=True)
    assert describe(retest) == (
        "Retake the placement test: last taken 70 days ago (a test is in progress, can be "
        "continued)"
    )
    assert describe(Candidate("vocab_review", "vocab_review", 0.5, count=12)) == (
        "Review words that are due: 12 due"
    )
    learn = Candidate("vocab_learn", "vocab_learn", 0.3, count=5, book=get_book("cet4"))
    assert describe(learn) == "Learn today's new words from CET-4: 5 left today"


def test_grammar_mistakes_are_quoted_with_their_own_quotes_neutralised() -> None:
    assert KC is not None
    practice = Candidate(
        f"grammar_practice:{KC.id}",
        "grammar_practice",
        0.4,
        count=3,
        kc=KC,
        p_mastery=0.23,
        examples=(Example('he "go" home', "he goes home"), Example("it work", None)),
    )

    text = describe(practice)

    assert "mastery 23%, 3 mistakes" in text
    assert 'mistake: "he \'go\' home" -> "he goes home"' in text
    assert text.endswith('mistake: "it work"')
