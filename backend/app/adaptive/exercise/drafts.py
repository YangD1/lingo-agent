"""What the generator and the critic write, and how code checks it (ADR 0021 §3).

Neither call uses a tagged union, which is not portable across providers' structured
output: the critic writes one flat review per item, and the generator one field per
position whose type lists only that format's fields (task 86.9). Code then assembles
each draft into its format's model in `formats.py`, so an item reaches the learner only
after `formats.py` has validated it and the critic has passed it.

The critic rates each item on the difficulty rubric of `rules.yaml`, and that rating is
the item's difficulty; the generator only aims at a target described in words, and no
item is rejected for landing away from it (ADR 0055 §4, revising Q33a). The critic
answers the closed formats
(choice4, cloze, find_fix) without the answer key, and code compares its answer with
the key, so "the answer is right and the only one" is checked by a second solver, not
taken on the critic's word.
"""

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from app.adaptive.elo import prior_difficulty
from app.adaptive.exercise.formats import (
    Choice4,
    Cloze,
    ConceptChoice,
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


# The kinds of error a find_fix item may plant (ADR 0055 §3): a missing word has no single
# wrong piece, so it is not one of them.
ERROR_KINDS = ("form", "word_choice")


class Draft(_Model):
    """Fields in the order a format's schema lists them: the self-check fields
    (`other_fillings`, `error_kind`) come before the key, so the model thinks before it
    writes the answer (ADR 0055 §3). They are for writing the item only: neither the
    learner nor the critic sees them."""

    position: int = Field(description="The position of the item this draft is for")
    format: Format
    question: str | None = Field(
        None, description="concept_choice, explain: the question about the rule"
    )
    stem: str | None = Field(
        None, description="choice4, cloze: the sentence with exactly one ___ for the gap"
    )
    hint: str | None = Field(None, description="cloze: e.g. the base form of the verb, or null")
    options: list[str] | None = Field(
        None, description="choice4, concept_choice: the four options, the correct one included"
    )
    segments: list[str] | None = Field(
        None,
        description="find_fix: the sentence in 3-6 consecutive pieces that join into it "
        "exactly (pieces carry their own spaces and punctuation); one piece is wrong",
    )
    error_kind: str | None = Field(
        None,
        description="find_fix: the kind of error planted, before you mark it: form (a wrong "
        "ending, tense, word order or pronoun) or word_choice (the wrong word of a pair). "
        "Never a missing word",
        json_schema_extra={"enum": list(ERROR_KINDS)},
    )
    instruction: str | None = Field(
        None, description="transform, translate, rewrite_own: what the learner is to do"
    )
    source: str | None = Field(
        None,
        description="transform: the English sentence to change; translate: the sentence "
        "in the learner's language",
    )
    other_fillings: list[str] | None = Field(
        None,
        description="choice4, cloze: before you write the answer, what else a learner might "
        "put in the gap and what in the sentence rules it out, one short line each "
        '(e.g. "am not: Look! shows it is happening")',
    )
    correct: str | None = Field(
        None, description="choice4, concept_choice: the correct option, as written"
    )
    wrong_segment: int | None = Field(None, description="find_fix: index of the wrong piece")
    key_points: list[str] | None = Field(
        None, description="explain: 1-4 points a good answer covers, as short phrases"
    )
    accepted: list[str] | None = Field(
        None,
        description="cloze: every right filling; find_fix: every right replacement for the "
        "wrong piece; transform, translate, rewrite_own: right full answers, best first",
    )
    explanation: str = Field(description="Why the answer is right, for after the learner answers")


def generated_set_model(rules: Rules, briefs: Sequence[ItemBrief]) -> type[BaseModel]:
    """The generator's output: one draft per position asked for, under `item_<position>`,
    each with only its format's fields. Its schema marks the fields a format needs as
    required and not null, while parsing still accepts a draft that leaves one out, so
    that draft goes back for a rewrite saying what is missing instead of failing the
    whole call: with one flat schema for every format, DeepSeek-V4-Flash left out a
    concept_choice's `options` and `correct` in every round (task 86.9)."""
    fields: dict[str, Any] = {
        f"item_{b.position}": (
            _item_model(b.item.format) | None,
            Field(None, description=f"The {b.item.format} item at position {b.position}"),
        )
        for b in briefs
    }
    return create_model(
        "GeneratedItems",
        __config__=ConfigDict(
            extra="ignore", frozen=True, json_schema_extra=_required_in_schema(tuple(fields))
        ),
        **fields,
    )


@cache
def _item_model(fmt: Format) -> type[BaseModel]:
    required = REQUIRED[fmt]
    wanted = {*required, *OPTIONAL.get(fmt, ())}
    fields: dict[str, Any] = {
        name: (
            info.annotation,
            Field(None, description=info.description, json_schema_extra=info.json_schema_extra),
        )
        for name, info in Draft.model_fields.items()
        if name in wanted
    }
    return create_model(
        f"Draft_{fmt}",
        __config__=ConfigDict(
            extra="ignore", frozen=True, json_schema_extra=_required_in_schema(required)
        ),
        **fields,
        explanation=(str, Field(description=_described("explanation"))),
    )


def _required_in_schema(names: tuple[str, ...]) -> Callable[[dict[str, Any]], None]:
    """Shows `names` to the model as required and not null; parsing still takes null."""

    def edit(schema: dict[str, Any]) -> None:
        for name in names:
            field = schema["properties"][name]
            field.pop("default", None)
            (kind,) = (k for k in field.pop("anyOf") if k.get("type") != "null")
            field.update(kind)
        schema["required"] = [*names, *schema.get("required", [])]

    return edit


def drafts_in(output: BaseModel, briefs: Sequence[ItemBrief]) -> list[Draft]:
    """The drafts of a `generated_set_model(rules, briefs)` output."""
    found = []
    for b in briefs:
        item: BaseModel | None = getattr(output, f"item_{b.position}", None)
        if item is None:
            continue
        data = {**item.model_dump(), "position": b.position, "format": b.item.format}
        found.append(Draft.model_validate(data))
    return found


def ratings_of(review: "Review") -> BaseModel:
    """The rubric ratings of a review made with `review_model`."""
    return cast(BaseModel, cast(Any, review).ratings)


class DraftError(ValueError):
    """A draft that does not make a valid item of its planned format."""


# The draft fields each format is assembled from, besides `explanation`: the generator
# is told them per item, in its brief and in the schema (task 86.9).
REQUIRED: Mapping[Format, tuple[str, ...]] = {
    "choice4": ("stem", "options", "other_fillings", "correct"),
    "cloze": ("stem", "other_fillings", "accepted"),
    "find_fix": ("segments", "error_kind", "wrong_segment", "accepted"),
    "transform": ("instruction", "source", "accepted"),
    "translate": ("source", "accepted"),
    "rewrite_own": ("instruction", "accepted"),
    "concept_choice": ("question", "options", "correct"),
    "explain": ("question", "key_points"),
}


# What a format may fill besides REQUIRED.
OPTIONAL: Mapping[Format, tuple[str, ...]] = {"cloze": ("hint",), "translate": ("instruction",)}


def fields_of(fmt: Format) -> list[str]:
    """What a draft of `fmt` must fill."""
    return [*REQUIRED[fmt], "explanation"]


def _missing(draft: Draft, fmt: Format) -> list[str]:
    return [f for f in REQUIRED[fmt] if getattr(draft, f) in (None, "", [])]


def _described(field: str) -> str | None:
    return Draft.model_fields[field].description


def _wanted(field: str) -> str:
    """What a field holds, without the formats its description starts with."""
    return (Draft.model_fields[field].description or field).partition(": ")[2]


def _problem(err: Any) -> str:
    """A validation error as the draft field it is about, for the rewrite: the item's
    own path (`concept_choice.content.options.0`) means nothing to the generator."""
    field = next((str(p) for p in reversed(err["loc"]) if str(p) in Draft.model_fields), None)
    if field is None:
        return str(err["msg"])
    return f"`{field}`: {err['msg']}"


def to_body(draft: Draft, brief: ItemBrief, rng: random.Random) -> ExerciseBody:
    """The item a draft describes, checked by its format's model. choice4 options are
    shuffled; rewrite_own takes the learner's sentence and its evidence id from the
    brief, never from the model."""
    fmt = brief.item.format
    if draft.format != fmt:
        raise DraftError(f"format is {draft.format}, planned {fmt}")
    if missing := _missing(draft, fmt):
        raise DraftError("; ".join(f"`{f}` is missing: {fmt} needs {_wanted(f)}" for f in missing))
    if fmt == "find_fix" and draft.error_kind not in ERROR_KINDS:
        raise DraftError(
            f"`error_kind` is {draft.error_kind!r}: find_fix only plants an error of form or "
            "word_choice; for a missing word write a new find_fix sentence with a wrong word "
            "instead"
        )
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
        case "concept_choice":
            options = list(draft.options or [])
            rng.shuffle(options)
            content = {"question": draft.question, "options": options}
            answer["correct"] = draft.correct
        case "explain":
            content = {"question": draft.question}
            answer["key_points"] = draft.key_points
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
        problems = dict.fromkeys(_problem(err) for err in e.errors())
        raise DraftError("; ".join(problems)) from e


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
        description="1. The item has a right answer, and for open formats the reference "
        "answers are right"
    )
    one_answer: bool = Field(
        description="2. Reading the whole sentence, only one answer fits: no second "
        "option, no other grammatical filling, only one wrong piece; for open formats, "
        "one clear way to do the task"
    )
    tests_kc: bool = Field(description="3. Answering needs the grammar point it is meant to test")
    form_hidden: bool = Field(
        description="3a. The instruction and hint do not give away the form being tested"
    )
    content_ok: bool = Field(
        description="4. Natural English, a clear instruction, no factual or cultural errors"
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


def reviews_in(output: BaseModel) -> list[Review]:
    """The reviews of a `critic_report_model` output."""
    return list(cast(Any, output).reviews)


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    # Why it failed, for the generator's rewrite and for `exercises.critic`.
    reasons: tuple[str, ...]
    # The critic's rubric difficulty and levels, which the item keeps.
    difficulty: float
    ratings: Mapping[str, str]
    # The critic's difficulty minus the planned target, kept for evaluation only.
    gap: float


def _solved(body: ExerciseBody, review: Review) -> str | None:
    """Why the critic's own answer shows a problem with a closed item, if it does."""
    match body:
        case Choice4() | ConceptChoice():
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
    target_difficulty: float,
    review: Review,
    rules: Rules,
) -> Verdict:
    """Pass only when the critic finds nothing wrong and solves a closed item as the key
    does. Its difficulty rating becomes the item's; how far it is from the target is
    recorded, never a reason to reject (ADR 0055 §4)."""
    critic_difficulty, levels = difficulty(kc, ratings_of(review), rules)
    reasons: list[str] = []
    for ok, name in (
        (review.answer_ok, "answer is not right"),
        (review.one_answer, "more than one answer fits"),
        (review.tests_kc, "does not test the grammar point"),
        (review.form_hidden, "the instruction or hint gives the tested form away"),
        (review.content_ok, "unnatural, unclear or factually wrong"),
    ):
        if not ok:
            reasons.append(name)
    if reasons:
        reasons.extend(p.strip() for p in review.problems if p.strip())
    if (unsolved := _solved(body, review)) is not None:
        reasons.append(unsolved)
    gap = round(critic_difficulty - target_difficulty, 2)
    return Verdict(not reasons, tuple(reasons), critic_difficulty, levels, gap)


def by_position[T: Draft | Review](items: Sequence[T], wanted: Sequence[int]) -> dict[int, T]:
    """The model's items for the wanted positions; the first wins when it repeats one,
    and any other position is ignored."""
    found: dict[int, T] = {}
    for item in items:
        if item.position in wanted and item.position not in found:
            found[item.position] = item
    return found
