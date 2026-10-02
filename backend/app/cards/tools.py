"""The tutor's tools (ADR 0015 §3): schemas the model sees, and validation of its calls.

A tool call never changes learner data. It becomes a card in the conversation: a
proposal the learner may apply (word book, learning goal), or a shortcut (practice, a
page). Arguments come from public catalogs only; ids of the learner, the conversation
or the turn are never arguments - the code running the tools already knows them.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.adaptive.kc.catalog import get_grammar_catalog
from app.memory.reflection import EXAM_TAGS
from app.services.vocab.books import BOOKS, get_book

# "writing" is put by writing_coach, not by a tool (task 38.5).
CardKind = Literal["word_book", "learning_goal", "practice", "link", "writing"]
LinkKind = Literal["vocab_review", "vocab_screen", "placement", "learner", "word_books"]
LINK_KINDS: tuple[LinkKind, ...] = (
    "vocab_review",
    "vocab_screen",
    "placement",
    "learner",
    "word_books",
)
# Mirrors the vocab API and the profile's check constraint.
MAX_DAILY_NEW = 200
MAX_DAILY_MINUTES = 600
MAX_GOAL_LENGTH = 200


def _enum(values: Collection[str]) -> dict[str, JsonValue]:
    """An enum for the schema the model sees (validated in `draft_card`, not here)."""
    options: list[JsonValue] = list(values)
    return {"enum": options}


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposeWordBook(_Args):
    """Propose switching the learner's word book, and optionally the number of new words
    a day. Shows a card the learner confirms or declines; nothing changes before they
    confirm, so never say it is done."""

    model_config = ConfigDict(title="propose_word_book")

    book_id: str = Field(
        description="The word book.", json_schema_extra=_enum([b.id for b in BOOKS])
    )
    daily_new: int | None = Field(
        default=None,
        ge=0,
        le=MAX_DAILY_NEW,
        description="New words a day; omit to keep the learner's current setting.",
    )


class ProposeLearningGoal(_Args):
    """Propose the learner's goal, target exam and daily study time. Shows a card the
    learner confirms or declines; nothing changes before they confirm. Include only the
    fields the learner actually agreed on."""

    model_config = ConfigDict(title="propose_learning_goal")

    goal: str | None = Field(
        default=None,
        max_length=MAX_GOAL_LENGTH,
        description="What the learner wants English for, in their words, briefly.",
    )
    target_exam: str | None = Field(
        default=None, json_schema_extra=_enum(sorted(EXAM_TAGS)), description="Exam tag."
    )
    daily_minutes: int | None = Field(
        default=None, ge=1, le=MAX_DAILY_MINUTES, description="Minutes a day."
    )


class SuggestPractice(_Args):
    """Show a card that starts a practice conversation on one grammar point."""

    model_config = ConfigDict(title="suggest_practice")

    kc_id: str = Field(description="Grammar point id, as given in your context.")


class SuggestLink(_Args):
    """Show a card linking to a page of the app: vocab_review (due words and new
    words), vocab_screen (mark words already known), placement (level test), learner
    (grammar mastery), word_books (choose a book)."""

    model_config = ConfigDict(title="suggest_link")

    kind: LinkKind


TOOL_SCHEMAS: tuple[type[_Args], ...] = (
    ProposeWordBook,
    ProposeLearningGoal,
    SuggestPractice,
    SuggestLink,
)
TOOL_NAMES: frozenset[str] = frozenset(str(t.model_config.get("title")) for t in TOOL_SCHEMAS)
_BY_NAME: dict[str, type[_Args]] = {str(t.model_config.get("title")): t for t in TOOL_SCHEMAS}


class ToolCallError(Exception):
    """A call the tools refuse; the message goes back to the model, so it must be safe
    to show and specific enough to correct the call."""


@dataclass(frozen=True)
class CardDraft:
    kind: CardKind
    params: dict[str, Any]

    @property
    def has_effect(self) -> bool:
        return self.kind in ("word_book", "learning_goal")


@dataclass(frozen=True)
class CardScope:
    """Limits of a conversation's suggestions; None fields allow anything valid.

    The planning conversation only suggests from the algorithm's candidates (§6)."""

    kc_ids: Collection[str] | None = None
    links: Collection[LinkKind] | None = None


def draft_card(name: str, args: Mapping[str, Any], scope: CardScope | None = None) -> CardDraft:
    """Validate one tool call and turn it into a card. Raises ToolCallError."""
    schema = _BY_NAME.get(name)
    if schema is None:
        raise ToolCallError(f"unknown tool {name!r}")
    try:
        parsed = schema.model_validate(args)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "arguments" for e in exc.errors()})
        raise ToolCallError(f"invalid arguments: {', '.join(fields)}") from exc
    scope = scope or CardScope()
    match parsed:
        case ProposeWordBook(book_id=book_id, daily_new=daily_new):
            if get_book(book_id) is None:
                raise ToolCallError(f"unknown book_id {book_id!r}")
            return CardDraft("word_book", {"book_id": book_id, "daily_new": daily_new})
        case ProposeLearningGoal():
            values = parsed.model_dump(exclude_none=True)
            if goal := values.get("goal"):
                values["goal"] = goal.strip()
            values = {k: v for k, v in values.items() if v != ""}
            if not values:
                raise ToolCallError("propose at least one of goal, target_exam, daily_minutes")
            # The enum is only in the schema the model sees; pydantic doesn't enforce it.
            if (exam := values.get("target_exam")) is not None and exam not in EXAM_TAGS:
                raise ToolCallError(f"unknown target_exam {exam!r}")
            return CardDraft("learning_goal", values)
        case SuggestPractice(kc_id=kc_id):
            if get_grammar_catalog().get(kc_id) is None:
                raise ToolCallError(f"unknown kc_id {kc_id!r}")
            if scope.kc_ids is not None and kc_id not in scope.kc_ids:
                raise ToolCallError(f"kc_id {kc_id!r} is not among the suggested grammar points")
            return CardDraft("practice", {"kc_id": kc_id})
        case SuggestLink(kind=kind):
            if scope.links is not None and kind not in scope.links:
                raise ToolCallError(f"link {kind!r} is not among the suggestions")
            return CardDraft("link", {"kind": kind})
    raise ToolCallError(f"unknown tool {name!r}")  # pragma: no cover


# --- what the graph sees ------------------------------------------------------------------


@dataclass(frozen=True)
class ToolOutcome:
    """One executed call: what goes back to the model, and what the learner sees."""

    content: str
    ok: bool
    # The card as the chat stream sends it; None when the call was refused.
    card: dict[str, Any] | None = None


class TutorTools(Protocol):
    """The tools of one turn, bound to its learner, conversation and turn (ADR 0013 §1)."""

    async def run(self, name: str, args: Mapping[str, Any], call_id: str) -> ToolOutcome: ...

    async def context(self) -> str:
        """The conversation's recent cards and their status, for the tutor's prompt."""
        ...
