"""What the generator and the critic write, and how code checks it (ADR 0021 §3).

Both calls use flat schemas rather than the per-format models of `formats.py`: a
tagged union is not portable across providers' structured output, while optional
fields are. Code then assembles each draft into its format's model, so an item reaches
the learner only after `formats.py` has validated it and the critic has passed it.

The generator rates each item on the difficulty rubric of `rules.yaml`; the critic
rates it again without seeing that rating. The critic answers the closed formats
(choice4, cloze, find_fix) without the answer key, and code compares its answer with
the key, so "the answer is right and the only one" is checked by a second solver, not
taken on the critic's word.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from app.adaptive.elo import prior_difficulty
from app.adaptive.exercise.formats import (
    Choice4,
    Cloze,
    ExerciseBody,
    FindFix,
    Format,
    normalize,
    parse_body,
)
from app.adaptive.exercise.inputs import ItemBrief
from app.adaptive.kc.catalog import GrammarKC
from app.adaptive.rules import Rules


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Rating(_Model):
    level: str
    reason: str = Field(description="One short sentence on why this level")


@cache
def _ratings_model(dimensions: tuple[tuple[str, str, tuple[str, ...]], ...]) -> type[BaseModel]:
    fields: dict[str, Any] = {
        name: (
            create_model(
                f"Rating_{name}",
                __base__=Rating,
                level=(Literal[levels], ...),
            ),
            Field(description=description),
        )
        for name, description, levels in dimensions
    }
    return create_model("Ratings", __base__=_Model, **fields)


def ratings_model(rules: Rules) -> type[BaseModel]:
    """The rubric of `rules.yaml` as a schema: one rating per dimension."""
    return _ratings_model(
        tuple(
            (name, dim.description, tuple(dim.levels))
            for name, dim in rules.difficulty.dimensions.items()
        )
    )


def difficulty(kc: GrammarKC, ratings: BaseModel, rules: Rules) -> tuple[float, dict[str, str]]:
    """The rubric difficulty of an item on `kc` and the levels it came from."""
    levels = {
        name: cast(Rating, getattr(ratings, name)).level for name in rules.difficulty.dimensions
    }
    return prior_difficulty(kc.cefr, levels, rules), levels


# --- the generator ---


class Draft(_Model):
    position: int = Field(description="The position of the item this draft is for")
    format: Format
    stem: str | None = Field(
        None, description="choice4, cloze: the sentence with exactly one ___ for the gap"
    )
    options: list[str] | None = Field(
        None, description="choice4: the four options, the correct one included"
    )
    correct: str | None = Field(None, description="choice4: the correct option, as written")
    hint: str | None = Field(None, description="cloze: e.g. the base form of the verb, or null")
    segments: list[str] | None = Field(
        None,
        description="find_fix: the sentence in 3-6 consecutive pieces that join into it "
        "exactly (pieces carry their own spaces and punctuation); one piece is wrong",
    )
    wrong_segment: int | None = Field(None, description="find_fix: index of the wrong piece")
    instruction: str | None = Field(
        None, description="transform, translate, rewrite_own: what the learner is to do"
    )
    source: str | None = Field(
        None,
        description="transform: the English sentence to change; translate: the sentence "
        "in the learner's language",
    )
    accepted: list[str] | None = Field(
        None,
        description="cloze: every right filling; find_fix: every right replacement for the "
        "wrong piece; transform, translate, rewrite_own: right full answers, best first",
    )
    explanation: str = Field(description="Why the answer is right, for after the learner answers")


def draft_model(rules: Rules) -> type[BaseModel]:
    return create_model("RatedDraft", __base__=Draft, ratings=(ratings_model(rules), ...))


def generated_set_model(rules: Rules) -> type[BaseModel]:
    """The generator's output: drafts for the positions it was asked for."""
    return create_model(
        "GeneratedItems",
        __base__=_Model,
        items=(list[draft_model(rules)], ...),  # type: ignore[misc]
    )


class DraftError(ValueError):
    """A draft that does not make a valid item of its planned format."""


def to_body(draft: Draft, brief: ItemBrief, rng: random.Random) -> ExerciseBody:
    """The item a draft describes, checked by its format's model. choice4 options are
    shuffled; rewrite_own takes the learner's sentence and its evidence id from the
    brief, never from the model."""
    fmt = brief.item.format
    if draft.format != fmt:
        raise DraftError(f"format is {draft.format}, planned {fmt}")
    content: dict[str, Any]
    answer: dict[str, Any] = {"explanation": draft.explanation}
    match fmt:
        case "choice4":
            options = list(draft.options or [])
            rng.shuffle(options)
            content = {"stem": draft.stem, "options": options}
            answer["correct"] = draft.correct
        case "cloze":
            content = {"stem": draft.stem, "hint": draft.hint or None}
            answer["accepted"] = draft.accepted
        case "find_fix":
            content = {"segments": draft.segments}
            answer |= {"wrong_segment": draft.wrong_segment, "accepted": draft.accepted}
        case "transform":
            content = {"instruction": draft.instruction, "source": draft.source}
            answer["accepted"] = draft.accepted
        case "translate":
            content = {"source": draft.source, "instruction": draft.instruction or None}
            answer["accepted"] = draft.accepted
        case "rewrite_own":
            own = brief.own_sentence
            assert own is not None  # briefs() sets it for rewrite_own
            content = {
                "instruction": draft.instruction,
                "original": own.original,
                "evidence_id": own.evidence_id,
            }
            answer["accepted"] = draft.accepted
    try:
        return parse_body(fmt, content, answer)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        )
        raise DraftError(problems) from e


# --- the critic ---


class Review(_Model):
    position: int
    own_answer: str = Field(
        description="Your own answer, written before judging: choice4 the option text, "
        "cloze the filling, find_fix the replacement for the wrong piece, otherwise a "
        "full sentence"
    )
    own_segment: int | None = Field(
        None, description="find_fix: index of the piece you think is wrong"
    )
    answer_ok: bool = Field(
        description="Exactly one right answer for closed formats; for open formats the "
        "reference answers are right and the task has a clear right way to do it"
    )
    tests_kc: bool = Field(description="Answering needs the grammar point it is meant to test")
    content_ok: bool = Field(
        description="Natural English, clear instructions, no factual or cultural errors"
    )
    problems: list[str] = Field(
        default_factory=list, description="What is wrong, one short sentence each"
    )


def review_model(rules: Rules) -> type[BaseModel]:
    return create_model("RatedReview", __base__=Review, ratings=(ratings_model(rules), ...))


def critic_report_model(rules: Rules) -> type[BaseModel]:
    return create_model(
        "CriticReport",
        __base__=_Model,
        reviews=(list[review_model(rules)], ...),  # type: ignore[misc]
    )


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    # Why it failed, for the generator's rewrite and for `exercises.critic`.
    reasons: tuple[str, ...]
    # The critic's rubric difficulty and levels, which the item keeps.
    difficulty: float
    ratings: Mapping[str, str]


def _solved(body: ExerciseBody, review: Review) -> str | None:
    """Why the critic's own answer shows a problem with a closed item, if it does."""
    match body:
        case Choice4():
            if normalize(review.own_answer) != normalize(body.answer.correct):
                return f"critic chose {review.own_answer!r}, key says {body.answer.correct!r}"
        case Cloze():
            if normalize(review.own_answer) not in {normalize(a) for a in body.answer.accepted}:
                return f"critic filled {review.own_answer!r}, not an accepted answer"
        case FindFix():
            if review.own_segment != body.answer.wrong_segment:
                return (
                    f"critic marked piece {review.own_segment}, "
                    f"key says {body.answer.wrong_segment}"
                )
    return None


def judge(
    body: ExerciseBody,
    kc: GrammarKC,
    generator_difficulty: float,
    review: Review,
    rules: Rules,
) -> Verdict:
    """Pass only when the critic finds nothing wrong, solves a closed item as the key
    does, and rates its difficulty close to the generator's rating (Q33a)."""
    critic_difficulty, levels = difficulty(kc, cast(Any, review).ratings, rules)
    reasons: list[str] = []
    for ok, name in (
        (review.answer_ok, "answer is not right or not the only one"),
        (review.tests_kc, "does not test the grammar point"),
        (review.content_ok, "unnatural, unclear or factually wrong"),
    ):
        if not ok:
            reasons.append(name)
    if reasons:
        reasons.extend(p.strip() for p in review.problems if p.strip())
    if (unsolved := _solved(body, review)) is not None:
        reasons.append(unsolved)
    gap = abs(critic_difficulty - generator_difficulty)
    if gap > rules.practice.critic_max_gap:
        reasons.append(
            f"difficulty ratings disagree: generator {generator_difficulty:+.1f}, "
            f"critic {critic_difficulty:+.1f}"
        )
    return Verdict(not reasons, tuple(reasons), critic_difficulty, levels)


def by_position[T: Draft | Review](items: Sequence[T], wanted: Sequence[int]) -> dict[int, T]:
    """The model's items for the wanted positions; the first wins when it repeats one,
    and any other position is ignored."""
    found: dict[int, T] = {}
    for item in items:
        if item.position in wanted and item.position not in found:
            found[item.position] = item
    return found
