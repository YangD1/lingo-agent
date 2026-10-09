"""The tutor's daily plan cards (ADR 0027 §1): a proposal for today's plan, kept within
what was open when the plan was drafted, with the minutes worked out by code."""

import dataclasses
from dataclasses import dataclass
from typing import Any

from app.adaptive.daily_plan.algorithm import (
    PlanChoice,
    PlanInputs,
    clamp,
    items,
    total_minutes,
)
from app.adaptive.rules import Rules


@dataclass(frozen=True, slots=True)
class PlanTarget:
    """The plan a card would replace: today's, with its limits."""

    plan_id: str
    # The learner's local day, ISO.
    day: str
    inputs: PlanInputs


def choice_of(params: dict[str, Any]) -> PlanChoice:
    return PlanChoice(**params["choice"])


def card_params(target: PlanTarget, choice: PlanChoice, rules: Rules) -> dict[str, Any]:
    """What the card holds: the plan it is for, the choice kept within today's limits,
    and its items with estimated minutes (for showing it, and for the model)."""
    kept = clamp(choice, target.inputs, rules)
    plan = items(kept, target.inputs, rules)
    return {
        "plan_id": target.plan_id,
        "day": target.day,
        "choice": dataclasses.asdict(kept),
        "items": [dataclasses.asdict(i) for i in plan],
        "minutes": round(total_minutes(plan), 1),
    }


def describe_params(params: dict[str, Any]) -> str:
    """One line for the model: what the plan asks for."""
    parts = []
    for item in params["items"]:
        match item["kind"]:
            case "review":
                parts.append(f"review {item['count']} words")
            case "new_words":
                parts.append(f"learn {item['count']} new words")
            case "practice":
                parts.append("one grammar practice set")
            case "reading":
                parts.append("read one article")
            case "writing":
                parts.append("write one short text")
    what = ", ".join(parts) if parts else "nothing"
    return f"today's plan: {what} (about {params['minutes']:g} min)"
