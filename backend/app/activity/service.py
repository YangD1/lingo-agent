"""Recording and reading agent activity (ADR 0013 §3).

Every step has a registered name, kind and summary schema. The schemas are the
whitelist of what may be shown to the learner: counts, KC ids, memory ids, the
learner's own words. Prompts, model output and error text never go in; a failure is
just `status="failed"`.
"""

import time
import uuid
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.kc.catalog import ErrorType
from app.adaptive.rules import Severity
from app.db.models import AgentActivity

type ActivityKind = Literal["step", "tool", "mcp", "background"]
type ActivityStatus = Literal["ok", "failed", "skipped"]


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextRead(Summary):
    """`load_context`: what the tutor was told about the learner this turn."""

    facts: list[uuid.UUID] = []
    episodes: list[uuid.UUID] = []
    profile_items: int = 0


class MemoryChanges(Summary):
    """`reflect_memory`: facts and profile fields reflection changed.

    Deleted facts are only counted: their content is gone, and so is their id's use.
    """

    added: list[uuid.UUID] = []
    updated: list[uuid.UUID] = []
    deleted: int = 0
    profile_fields: list[str] = []


class GrammarMistake(Summary):
    kc_id: str
    error_type: ErrorType
    severity: Severity
    original: str
    correction: str | None = None


class GrammarTags(Summary):
    """`grammar_tagging`: one learner message's tagged mistakes and successes."""

    mistakes: list[GrammarMistake] = []
    used_correctly: list[str] = []


class CollectedWord(Summary):
    word_id: int
    word: str


class WordsCollected(Summary):
    """`vocab_collect`: words from one learner message put on their word list, and
    those left alone because the learner already had a card for them."""

    added: list[CollectedWord] = []
    existing: list[CollectedWord] = []


class SummaryUpdate(Summary):
    """`summarize`: the conversation summary was rewritten."""

    episode_id: uuid.UUID | None = None


@dataclass(frozen=True)
class StepSpec:
    kind: ActivityKind
    summary: type[Summary]


STEPS: dict[str, StepSpec] = {
    "load_context": StepSpec("step", ContextRead),
    "reflect_memory": StepSpec("background", MemoryChanges),
    "grammar_tagging": StepSpec("background", GrammarTags),
    "vocab_collect": StepSpec("background", WordsCollected),
    "summarize": StepSpec("background", SummaryUpdate),
}


@dataclass(frozen=True)
class Step:
    """One step of a turn, as the code that ran it reports it."""

    name: str
    status: ActivityStatus = "ok"
    summary: Summary | None = None
    duration_ms: int | None = None
    call_id: str = ""

    def payload(self, turn_id: str) -> dict[str, Any]:
        """What the chat stream sends live; the same fields the activity API returns."""
        return {
            "turn_id": turn_id,
            "name": self.name,
            "kind": STEPS[self.name].kind,
            "call_id": self.call_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "summary": _summary_json(self.name, self.status, self.summary),
        }


class ActivitySink(Protocol):
    """Where the steps of one turn are recorded; bound to its learner, conversation
    and turn, so the graph never handles those ids (ADR 0013 §1)."""

    turn_id: str

    async def record(self, step: Step) -> None: ...


class DatabaseActivity:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        turn_id: str,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._conversation_id = conversation_id
        self.turn_id = turn_id

    async def record(self, step: Step) -> None:
        async with self._sessionmaker() as session:
            await record(
                session,
                user_id=self._user_id,
                conversation_id=self._conversation_id,
                turn_id=self.turn_id,
                name=step.name,
                status=step.status,
                summary=step.summary,
                duration_ms=step.duration_ms,
                call_id=step.call_id,
            )
            await session.commit()


async def record(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_id: str,
    name: str,
    status: ActivityStatus = "ok",
    summary: Summary | None = None,
    duration_ms: int | None = None,
    call_id: str = "",
) -> None:
    """Write one step of a turn, replacing an earlier write of it; does not commit."""
    values = {
        "kind": STEPS[name].kind,
        "status": status,
        "duration_ms": duration_ms,
        "summary": _summary_json(name, status, summary),
    }
    await session.execute(
        insert(AgentActivity)
        .values(
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            name=name,
            call_id=call_id,
            **values,
        )
        .on_conflict_do_update(
            index_elements=["conversation_id", "turn_id", "name", "call_id"], set_=values
        )
    )


def _summary_json(name: str, status: ActivityStatus, summary: Summary | None) -> dict[str, Any]:
    expected = STEPS[name].summary
    if summary is not None and not isinstance(summary, expected):
        raise TypeError(f"{name} takes a {expected.__name__}, not {type(summary).__name__}")
    # Failed and skipped steps say nothing beyond that.
    if summary is None or status != "ok":
        return {}
    return summary.model_dump(mode="json")


async def list_activities(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_ids: Collection[str] | None = None,
) -> Sequence[AgentActivity]:
    """A conversation's activity in the order it happened; unknown step names (from a
    newer version, rolled back) are left out."""
    query = select(AgentActivity).where(
        AgentActivity.user_id == user_id,
        AgentActivity.conversation_id == conversation_id,
        AgentActivity.name.in_(STEPS),
    )
    if turn_ids is not None:
        query = query.where(AgentActivity.turn_id.in_(turn_ids))
    rows = await session.scalars(query.order_by(AgentActivity.created_at, AgentActivity.id))
    return rows.all()


def parse_summary(row: AgentActivity) -> Summary:
    return STEPS[row.name].summary.model_validate(row.summary)


def memory_refs(summary: Summary) -> list[uuid.UUID]:
    """The memories a summary refers to, to be shown with their current content."""
    match summary:
        case ContextRead():
            return [*summary.facts, *summary.episodes]
        case MemoryChanges():
            return [*summary.added, *summary.updated]
        case SummaryUpdate(episode_id=uuid.UUID() as episode_id):
            return [episode_id]
    return []


def word_refs(summary: Summary) -> list[int]:
    """Words a summary says were added, to be shown as still on the list or removed."""
    if isinstance(summary, WordsCollected):
        return [w.word_id for w in summary.added]
    return []


def kc_refs(summary: Summary) -> list[str]:
    if isinstance(summary, GrammarTags):
        return [m.kc_id for m in summary.mistakes] + summary.used_correctly
    return []


async def untag(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    turn_id: str,
    kc_id: str,
    correct: bool,
    original: str | None,
) -> None:
    """Drop one tagged item from a turn's `grammar_tagging`, after the learner deleted
    the evidence behind it, so no copy of it is left; does not commit."""
    row = await session.scalar(
        select(AgentActivity)
        .where(
            AgentActivity.user_id == user_id,
            AgentActivity.turn_id == turn_id,
            AgentActivity.name == "grammar_tagging",
        )
        .with_for_update()
    )
    if row is None or row.status != "ok":
        return
    tags = GrammarTags.model_validate(row.summary)
    if correct:
        kept = tags.model_copy(
            update={"used_correctly": [k for k in tags.used_correctly if k != kc_id]}
        )
    else:
        mistakes = list(tags.mistakes)
        match = next((m for m in mistakes if m.kc_id == kc_id and m.original == original), None)
        if match is not None:
            mistakes.remove(match)
        kept = tags.model_copy(update={"mistakes": mistakes})
    row.summary = kept.model_dump(mode="json")


async def forget_grammar_tags(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete every `grammar_tagging` row of a learner, with the learner model; does
    not commit. Their summaries quote the learner's mistakes."""
    await session.execute(
        delete(AgentActivity).where(
            AgentActivity.user_id == user_id, AgentActivity.name == "grammar_tagging"
        )
    )


class Stopwatch:
    ms: int | None = None


@contextmanager
def timed() -> Iterator[Stopwatch]:
    """`with timed() as t: ...` then `t.ms`; set even when the block raises."""
    watch = Stopwatch()
    start = time.perf_counter()
    try:
        yield watch
    finally:
        watch.ms = round((time.perf_counter() - start) * 1000)
