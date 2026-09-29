"""Post-turn reflection: what the tutor should remember (ADR 0009 §3).

The model proposes; code decides. Its output is a structured list of operations on
short ids (`m1`, `m2`, ...) that map to this learner's memories only, so it can neither
touch another learner's rows nor invent an id. Profile updates are sanitised field by
field, and the CEFR level is never taken from here (levels come from assessment).
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile
from app.memory import service
from app.memory.context import profile_lines
from app.memory.embedding import MemoryEmbedder
from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_structured_llm

logger = logging.getLogger(__name__)

REFLECT_TASK = "reflect"
# Guards against a model that turns one exchange into a dozen "facts".
MAX_ADDS_PER_TURN = 5
MAX_FACTS = 100
# Per message, when rendering transcripts for the model.
MAX_MESSAGE_CHARS = 2000
MAX_SUMMARY_INPUT_CHARS = 12_000
# Word book tags of ADR 0011; anything else from the model is dropped.
EXAM_TAGS = frozenset({"zk", "gk", "cet4", "cet6", "ky", "toefl", "ielts", "gre"})


# The UI's locale cookie (ADR 0006) decides the language memories are written in, so
# the learner can read and edit them on the memory page.
LOCALE_COOKIE = "NEXT_LOCALE"
_LANGUAGE_BY_LOCALE = {"zh-CN": "Simplified Chinese", "en": "English"}


def memory_language(locale: str | None) -> str:
    return _LANGUAGE_BY_LOCALE.get(locale or "", "English")


class MemoryOp(BaseModel):
    action: Literal["add", "update", "delete"]
    id: str | None = Field(
        default=None, description="Id of an existing fact, e.g. 'm3'; for update and delete"
    )
    content: str | None = Field(
        default=None, description="The fact as one short sentence; for add and update"
    )


class ProfileUpdate(BaseModel):
    native_language: str | None = None
    occupation: str | None = None
    goal: str | None = Field(default=None, description="What the learner wants English for")
    target_exam: str | None = Field(
        default=None, description="One of: zk, gk, cet4, cet6, ky, toefl, ielts, gre"
    )
    interests: list[str] | None = None
    daily_minutes: int | None = Field(default=None, description="Planned study time per day")
    explanation_language: Literal["zh", "en"] | None = Field(
        default=None, description="Language the learner wants grammar explained in"
    )


class Reflection(BaseModel):
    memory_ops: list[MemoryOp] = Field(default_factory=list)
    profile_updates: ProfileUpdate | None = None


class EpisodeSummary(BaseModel):
    summary: str = Field(description="The new running summary, at most 80 words")


@dataclass(frozen=True)
class KnownFact:
    """A remembered fact, detached from any session."""

    id: uuid.UUID
    content: str


@dataclass(frozen=True)
class Applied:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    profile_fields: tuple[str, ...] = ()


def fact_ids(facts: Sequence[KnownFact]) -> dict[str, uuid.UUID]:
    """Short ids for the prompt: fewer tokens than UUIDs, and nothing to hallucinate."""
    return {f"m{i}": fact.id for i, fact in enumerate(facts, start=1)}


def render_messages(messages: Sequence[BaseMessage]) -> str:
    lines = []
    for message in messages:
        speaker = "Learner" if isinstance(message, HumanMessage) else "Tutor"
        text = message.text.strip()
        if len(text) > MAX_MESSAGE_CHARS:
            text = text[:MAX_MESSAGE_CHARS] + " […]"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines) or "(none)"


def reflection_input(
    *,
    profile: UserProfile | None,
    facts: Sequence[KnownFact],
    earlier: Sequence[BaseMessage],
    new: Sequence[BaseMessage],
    language: str,
) -> str:
    by_id = {v: k for k, v in fact_ids(facts).items()}
    profile_text = "\n".join(
        f"- {label}: {value}"
        for label, value in (profile_lines(profile) if profile else {}).items()
    )
    facts_text = "\n".join(f"{by_id[f.id]}: {f.content}" for f in facts)
    return (
        f"Write facts in: {language}\n\n"
        f"## Current profile\n{profile_text or '(empty)'}\n\n"
        f"## Remembered facts\n{facts_text or '(none)'}\n\n"
        f"## Earlier messages (context only)\n{render_messages(earlier)}\n\n"
        f"## New messages to reflect on\n{render_messages(new)}"
    )


async def reflect(ctx: TenantProviderContext, prompt: str, config: RunnableConfig) -> Reflection:
    llm = get_structured_llm(ctx, REFLECT_TASK, Reflection)
    return await llm.ainvoke(
        [SystemMessage(load_prompt("reflect")), HumanMessage(prompt)], config=config
    )


async def summarize(
    ctx: TenantProviderContext,
    *,
    previous: str,
    messages: Sequence[BaseMessage],
    language: str,
    config: RunnableConfig,
) -> str:
    transcript = render_messages(messages)
    if len(transcript) > MAX_SUMMARY_INPUT_CHARS:  # keep the most recent part
        transcript = "[…]\n" + transcript[-MAX_SUMMARY_INPUT_CHARS:]
    prompt = (
        f"Write the summary in: {language}\n\n"
        f"## Previous summary\n{previous or '(none)'}\n\n"
        f"## Messages since then\n{transcript}"
    )
    llm = get_structured_llm(ctx, REFLECT_TASK, EpisodeSummary)
    result = await llm.ainvoke(
        [SystemMessage(load_prompt("reflect_summary")), HumanMessage(prompt)], config=config
    )
    return result.summary


async def apply_reflection(
    session: AsyncSession,
    reflection: Reflection,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    facts: Sequence[KnownFact],
    embedder: MemoryEmbedder | None,
) -> Applied:
    """Carry out the operations; `facts` must be the list the model was shown."""
    ids = fact_ids(facts)
    known = {_normalized(f.content) for f in facts}
    added = updated = deleted = 0
    touched: set[uuid.UUID] = set()
    for op in reflection.memory_ops:
        try:
            if op.action == "add":
                if added >= MAX_ADDS_PER_TURN or len(facts) + added >= MAX_FACTS:
                    continue
                if _normalized(op.content or "") in known:
                    continue
                known.add(_normalized(op.content or ""))
                await service.add_memory(
                    session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    kind="fact",
                    content=op.content or "",
                    source_conversation_id=conversation_id,
                    embedder=embedder,
                )
                added += 1
                continue
            memory_id = ids.get(op.id or "")
            if memory_id is None or memory_id in touched:
                logger.info("reflection referred to unknown or repeated fact %r", op.id)
                continue
            touched.add(memory_id)
            if op.action == "update":
                await service.update_memory(
                    session, user_id, memory_id, op.content or "", embedder=embedder
                )
                updated += 1
            else:
                await service.delete_memory(session, user_id, memory_id)
                deleted += 1
        except (ValueError, service.MemoryNotFoundError):
            # Empty or overlong content, or the learner deleted it meanwhile.
            await session.rollback()
            logger.info("skipped a %s memory operation", op.action, exc_info=True)
    changes = profile_changes(reflection.profile_updates)
    if changes:
        await service.update_profile(session, user_id, changes, by_learner=False)
    return Applied(added, updated, deleted, tuple(sorted(changes)))


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip(".")


def profile_changes(update: ProfileUpdate | None) -> dict[str, object]:
    """The fields worth writing, each cleaned or dropped."""
    if update is None:
        return {}
    changes: dict[str, object] = {}
    for field in ("native_language", "occupation", "goal"):
        value = getattr(update, field)
        if isinstance(value, str) and value.strip():
            changes[field] = value.strip()[: 50 if field == "native_language" else 200]
    if update.target_exam and update.target_exam.strip().lower() in EXAM_TAGS:
        changes["target_exam"] = update.target_exam.strip().lower()
    if update.interests is not None:
        interests = [i.strip()[:100] for i in update.interests if i.strip()]
        changes["interests"] = list(dict.fromkeys(interests))[:20]
    if update.daily_minutes is not None and 1 <= update.daily_minutes <= 600:
        changes["daily_minutes"] = update.daily_minutes
    if update.explanation_language is not None:
        changes["explanation_language"] = update.explanation_language
    return changes
