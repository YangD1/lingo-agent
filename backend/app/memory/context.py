"""What the tutor is told about the learner on each turn (ADR 0009 §4).

Rendered into that call's system prompt only: it travels through the graph in an
untracked channel, so the checkpoint never holds a copy, and a memory the learner
deletes is gone from the very next turn.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.kc.catalog import get_grammar_catalog
from app.adaptive.rules import get_rules
from app.db.models import UserProfile
from app.memory import service
from app.memory.embedding import MemoryEmbedder
from app.memory.language import DEFAULT_CHAT_LANGUAGE, ChatLanguage, chat_language
from app.memory.progress import load_progress, render_progress

logger = logging.getLogger(__name__)

# Facts are budgeted in estimated tokens (ADR 0053 §3), so Chinese and English facts
# get about the same share; summaries are clipped by characters.
MAX_FACTS_TOKENS = 1200
MAX_EPISODE_CHARS = 600
EPISODES_IN_CONTEXT = 3

_LANGUAGES = {"zh": "Chinese", "en": "English"}


@dataclass(frozen=True)
class LearnerContext:
    profile: dict[str, str] = field(default_factory=dict)  # label -> value, only set ones
    facts: Sequence[str] = ()
    episodes: Sequence[str] = ()
    # Memory ids in the same order, for the learner-facing activity (ADR 0013 §3).
    fact_ids: Sequence[uuid.UUID] = ()
    episode_ids: Sequence[uuid.UUID] = ()
    # The language the tutor mainly talks in (ADR 0017 §1); by level until they choose.
    chat_language: ChatLanguage = DEFAULT_CHAT_LANGUAGE
    # Where they stand now, counted by code (ADR 0052 §1), already rendered; empty
    # when it could not be read.
    progress: str = ""

    def is_empty(self) -> bool:
        return not (self.profile or self.facts or self.episodes or self.progress)


class LearnerSource(Protocol):
    async def load(self, query: str) -> LearnerContext:
        """`query` is the learner's latest message, used to pick related episodes."""
        ...


class DatabaseLearner:
    """LearnerSource over one learner's rows; `conversation_id` is the current one,
    whose own summary is left out (its messages are already in the prompt). None: no
    conversation yet (a realtime call is set up before its conversation exists).
    `progress_days` False leaves the last days out of the progress section: the daily
    conversation's brief has them already. `suggestions` adds the learning engine's
    next steps to it, for free chat (ADR 0054 §4)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        user_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        embedder: MemoryEmbedder | None,
        *,
        progress_days: bool = True,
        suggestions: bool = False,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._embedder = embedder
        self._progress_days = progress_days
        self._suggestions = suggestions

    async def load(self, query: str) -> LearnerContext:
        async with self._sessionmaker() as session:
            profile = await service.get_profile(session, self._user_id)
            since = (
                await service.sitting_started_at(session, self._conversation_id)
                if self._conversation_id
                else None
            )
            facts = await service.facts_for_context(session, self._user_id, sitting_since=since)
            episodes = await service.relevant_episodes(
                session,
                self._user_id,
                query,
                embedder=self._embedder,
                limit=EPISODES_IN_CONTEXT,
                exclude_conversation_id=self._conversation_id,
            )
        return LearnerContext(
            profile=profile_lines(profile) if profile else {},
            facts=[m.content for m in facts],
            episodes=[m.content for m in episodes],
            fact_ids=[m.id for m in facts],
            episode_ids=[m.id for m in episodes],
            chat_language=chat_language(
                profile.chat_language if profile else None,
                profile.cefr_level if profile else None,
            ),
            progress=await self._progress(),
        )

    async def _progress(self) -> str:
        """Its own session: a failed query must not cost the memories (or the turn)."""
        try:
            async with self._sessionmaker() as session:
                found = await load_progress(
                    session,
                    self._user_id,
                    rules=get_rules(),
                    catalog=get_grammar_catalog(),
                    suggest=self._suggestions,
                )
                await session.commit()  # stale mastery rows may have been rebuilt
        except Exception:
            logger.exception("loading the learner's progress failed")
            return ""
        return render_progress(found, days=self._progress_days)


def profile_lines(profile: UserProfile) -> dict[str, str]:
    values: dict[str, str | None] = {
        "Native language": profile.native_language,
        "Occupation": profile.occupation,
        "Goal": profile.goal,
        "Target exam": profile.target_exam.upper() if profile.target_exam else None,
        "Interests": ", ".join(profile.interests) if profile.interests else None,
        "Daily study time": f"{profile.daily_minutes} minutes" if profile.daily_minutes else None,
        "CEFR level": profile.cefr_level,
        "Explain grammar in": _LANGUAGES.get(profile.explanation_language or ""),
    }
    return {label: value for label, value in values.items() if value}


def render_learner_context(context: LearnerContext) -> str:
    """Markdown for the system prompt; empty when there is nothing to say."""
    if context.is_empty():
        return ""
    sections: list[str] = []
    if context.profile:
        lines = [f"- {label}: {value}" for label, value in context.profile.items()]
        sections.append("### Profile\n" + "\n".join(lines))
    # What stays the same within a sitting comes first, so the prompt keeps a common
    # prefix the vendor can cache (ADR 0053 §2); progress changes with every answer.
    if shown := facts_shown(context.facts):
        lines = [f"- {fact}" for fact in context.facts[:shown]]
        sections.append("### Things they have told you\n" + "\n".join(lines))
    if context.progress:
        sections.append("### Where they are now (counted by the app)\n" + context.progress)
    if context.episodes:
        lines = [f"- {_clip(e, MAX_EPISODE_CHARS)}" for e in context.episodes]
        sections.append("### Earlier conversations\n" + "\n".join(lines))
    return "\n\n".join(sections)


def facts_shown(facts: Sequence[str]) -> int:
    """How many facts fit MAX_FACTS_TOKENS. Newest come first, so the oldest are dropped."""
    used = 0
    for count, fact in enumerate(facts):
        used += estimated_tokens(fact)
        if used > MAX_FACTS_TOKENS:
            return count
    return len(facts)


def estimated_tokens(text: str) -> int:
    """A token per CJK character, one per 4 other characters: only for budgeting."""
    wide = sum(1 for ch in text if _is_wide(ch))
    return wide + -(-(len(text) - wide) // 4)


def _is_wide(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF  # kana
        or 0x3400 <= code <= 0x9FFF  # CJK ideographs
        or 0xAC00 <= code <= 0xD7AF  # hangul
        or 0xF900 <= code <= 0xFAFF
        or 0xFF00 <= code <= 0xFFEF  # full-width forms and punctuation
        or 0x3000 <= code <= 0x303F  # CJK punctuation
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
