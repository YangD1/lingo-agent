"""What writing_coach is told about a review (task 38.5)."""

from app.chat.writing import outcome
from app.db.models import WritingSubmission
from app.prompts import load_prompt

CARD = {"id": "c1", "kind": "writing"}


def submission(status: str, **fields: object) -> WritingSubmission:
    return WritingSubmission(id=7, status=status, text="...", word_count=60, **fields)


def test_a_review_still_running_is_shown_on_the_card() -> None:
    result = outcome(submission("pending"), CARD)

    assert (result.status, result.card) == ("ok", CARD)
    assert result.summary is not None and result.summary.mistakes == 0
    assert load_prompt("writing_pending") in result.guidance


def test_a_failed_review_keeps_the_card() -> None:
    result = outcome(submission("failed", error_code="review_failed"), CARD)

    assert (result.status, result.card) == ("failed", CARD)
    assert load_prompt("writing_failed") in result.guidance


def test_the_most_serious_corrections_come_first() -> None:
    def mistake(severity: str, original: str) -> dict[str, str]:
        return {
            "kc_id": "g.past_simple_regular",
            "severity": severity,
            "original": original,
            "correction": "x",
            "explanation": "why",
        }

    row = submission(
        "done",
        summary="Clear story.",
        scores={"grammar": {"score": 3, "reason": "tense slips"}},
        corrections=[
            {"mistakes": [mistake("low", "a")]},
            {"mistakes": [mistake("high", "b")]},
        ],
    )

    result = outcome(row, CARD)

    assert result.summary is not None and result.summary.mistakes == 2
    assert "Clear story." in result.guidance and "grammar: 3 (tense slips)" in result.guidance
    assert result.guidance.index('"b"') < result.guidance.index('"a"')
    assert "{review}" not in result.guidance
