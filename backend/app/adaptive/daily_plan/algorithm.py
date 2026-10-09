"""Drafting and checking a day's plan (ADR 0027 §2-§3). Pure functions over numbers
read elsewhere; every tuning number comes from `rules.yaml` (`daily_plan:`)."""

import math
from dataclasses import dataclass
from typing import Literal

from app.adaptive.rules import Rules

ItemKind = Literal["review", "new_words", "practice", "reading", "writing"]
# The order items are planned in and shown.
ITEM_KINDS: tuple[ItemKind, ...] = ("review", "practice", "new_words", "reading", "writing")
# Rounding guard: 0.6 * 20 / 0.25 must count as 48, not 47.
_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class PlanInputs:
    """What the learner has to do today, read when the plan is drafted."""

    # The profile's daily minutes; None = not set.
    minutes: int | None
    reviews_due: int
    # New words the word book still allows today (0 without a book).
    new_left: int
    # The grammar point the next practice set would start with; None = nothing to practise.
    practice_kc: str | None
    # An article ready at the learner's level; None = no subscription or nothing new.
    article_id: str | None
    # Whole days since the last essay; None = never wrote.
    days_since_writing: int | None


@dataclass(frozen=True, slots=True)
class PlanChoice:
    """What a plan asks for: the numbers a card shows and the learner may adjust."""

    review: int = 0
    new_words: int = 0
    practice: bool = False
    reading: bool = False
    writing: bool = False


@dataclass(frozen=True, slots=True)
class PlanItem:
    kind: ItemKind
    minutes: float
    # Reviews and new words; None for the one-off items.
    count: int | None = None
    # The grammar point (practice) or article (reading) the item links to.
    ref: str | None = None


def budget(inputs: PlanInputs, rules: Rules) -> int:
    return inputs.minutes or rules.daily_plan.default_minutes


def _fits(minutes: float, per: float) -> int:
    return max(0, math.floor(minutes / per + _EPS))


def draft(inputs: PlanInputs, rules: Rules) -> PlanChoice:
    """Fill the learner's minutes in order: reviews (capped at `review_share`), one
    practice set, new words, an article, an essay; leftover time goes back to reviews."""
    r = rules.daily_plan
    per = r.minutes
    total = budget(inputs, rules)

    review = min(inputs.reviews_due, _fits(total * r.review_share, per.review))
    left = total - review * per.review

    practice = inputs.practice_kc is not None and left + _EPS >= per.practice
    if practice:
        left -= per.practice

    new_words = min(inputs.new_left, _fits(left, per.new_word))
    left -= new_words * per.new_word

    reading = inputs.article_id is not None and left + _EPS >= per.reading
    if reading:
        left -= per.reading

    writing = (
        total >= r.writing_min_minutes
        and (inputs.days_since_writing is None or inputs.days_since_writing >= r.writing_gap_days)
        and left + _EPS >= per.writing
    )
    if writing:
        left -= per.writing

    review += min(inputs.reviews_due - review, _fits(left, per.review))
    return PlanChoice(review, new_words, practice, reading, writing)


def clamp(choice: PlanChoice, inputs: PlanInputs, rules: Rules) -> PlanChoice:
    """Keep an adjusted plan (the learner's or the tutor's) within what can be done today:
    no more reviews than are due or new words than the book allows, no practice or
    reading without something to practise or read."""
    cap = rules.daily_plan.max_count
    return PlanChoice(
        review=max(0, min(choice.review, inputs.reviews_due, cap)),
        new_words=max(0, min(choice.new_words, inputs.new_left, cap)),
        practice=choice.practice and inputs.practice_kc is not None,
        reading=choice.reading and inputs.article_id is not None,
        writing=choice.writing,
    )


def items(choice: PlanChoice, inputs: PlanInputs, rules: Rules) -> tuple[PlanItem, ...]:
    """The plan's items in order, with estimated minutes; empty ones are left out."""
    per = rules.daily_plan.minutes
    out: list[PlanItem] = []
    if choice.review:
        out.append(PlanItem("review", choice.review * per.review, count=choice.review))
    if choice.practice:
        out.append(PlanItem("practice", per.practice, ref=inputs.practice_kc))
    if choice.new_words:
        out.append(PlanItem("new_words", choice.new_words * per.new_word, count=choice.new_words))
    if choice.reading:
        out.append(PlanItem("reading", per.reading, ref=inputs.article_id))
    if choice.writing:
        out.append(PlanItem("writing", per.writing))
    return tuple(out)


def total_minutes(plan: tuple[PlanItem, ...]) -> float:
    return sum(i.minutes for i in plan)
