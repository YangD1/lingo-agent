"""Which coach answers a conversation (ADR 0023 §3, task 37.1)."""

from app.agents.routing import Route, route_for


def test_practice_conversations_go_to_grammar_coach() -> None:
    assert route_for("g.past_simple_irregular") is Route.GRAMMAR_COACH


def test_free_planning_and_daily_conversations_stay_with_the_tutor() -> None:
    # Planning and daily conversations have no grammar point: the tutor answers them,
    # with their brief and limited tools.
    assert route_for(None) is Route.TUTOR
