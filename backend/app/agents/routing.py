"""Which coach answers a turn (ADR 0023 §3).

The route comes from what is certain about the conversation, without a model call: a
practice conversation (it has a grammar point) goes to grammar_coach, everything else,
planning and daily conversations included, to the tutor. Free chat will be classified
by the `route` task once there is another coach to hand it to (writing, task 38, Q37a).
"""

from enum import StrEnum


class Route(StrEnum):
    TUTOR = "tutor"
    GRAMMAR_COACH = "grammar_coach"


def route_for(focus_kc_id: str | None) -> Route:
    """The coach of a conversation, from its grammar point (planning and daily
    conversations are the tutor's, with their brief and limited tools)."""
    return Route.GRAMMAR_COACH if focus_kc_id is not None else Route.TUTOR
