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
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import ErrorType
from app.adaptive.rules import Severity
from app.db.models import AgentActivity

type ActivityKind = Literal["step", "tool", "mcp", "background"]
type ActivityStatus = Literal["ok", "failed", "skipped"]


class _Summary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextRead(_Summary):
    """`load_context`: what the tutor was told about the learner this turn."""

    facts: list[uuid.UUID] = []
    episodes: list[uuid.UUID] = []
    profile_fields: list[str] = []


class MemoryChanges(_Summary):
    """`reflect_memory`: facts and profile fields reflection changed.

    Deleted facts are only counted: their content is gone, and so is their id's use.
    """

    added: list[uuid.UUID] = []
    updated: list[uuid.UUID] = []
    deleted: int = 0
    profile_fields: list[str] = []


class GrammarMistake(_Summary):
    kc_id: str
    error_type: ErrorType
    severity: Severity
    original: str
    correction: str | None = None


class GrammarTags(_Summary):
    """`grammar_tagging`: one learner message's tagged mistakes and successes."""

    mistakes: list[GrammarMistake] = []
    used_correctly: list[str] = []


class SummaryUpdate(_Summary):
    """`summarize`: the conversation summary was rewritten."""

    episode_id: uuid.UUID | None = None


@dataclass(frozen=True)
class StepSpec:
    kind: ActivityKind
    summary: type[_Summary]


STEPS: dict[str, StepSpec] = {
    "load_context": StepSpec("step", ContextRead),
    "reflect_memory": StepSpec("background", MemoryChanges),
    "grammar_tagging": StepSpec("background", GrammarTags),
    "summarize": StepSpec("background", SummaryUpdate),
}


async def record(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_id: str,
    name: str,
    status: ActivityStatus = "ok",
    summary: _Summary | None = None,
    duration_ms: int | None = None,
    call_id: str = "",
) -> None:
    """Write one step of a turn, replacing an earlier write of it; does not commit."""
    spec = STEPS[name]
    if summary is not None and not isinstance(summary, spec.summary):
        raise TypeError(f"{name} takes a {spec.summary.__name__}, not {type(summary).__name__}")
    values = {
        "kind": spec.kind,
        "status": status,
        "duration_ms": duration_ms,
        # Failed and skipped steps say nothing beyond that.
        "summary": summary.model_dump(mode="json") if summary and status == "ok" else {},
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


def parse_summary(row: AgentActivity) -> _Summary:
    return STEPS[row.name].summary.model_validate(row.summary)


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
