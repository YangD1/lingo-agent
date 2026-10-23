"""Reading stored follow-up limits (ADR 0064 §5)."""

from app.chat.deepen import DEFAULT_DEEPEN, deepen_settings


def test_missing_values_take_the_defaults() -> None:
    assert deepen_settings(None) == DEFAULT_DEEPEN
    assert deepen_settings({"max_tokens": 4000}).model_dump() == {
        **DEFAULT_DEEPEN.model_dump(),
        "max_tokens": 4000,
    }


def test_a_row_out_of_bounds_falls_back_to_the_defaults() -> None:
    # Written before a bound was tightened, or by hand: never an unbounded wait.
    assert deepen_settings({"total_seconds": 3600}) == DEFAULT_DEEPEN
    assert deepen_settings({"retired_field": 1}) == DEFAULT_DEEPEN
