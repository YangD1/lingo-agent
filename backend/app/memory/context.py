"""What the tutor is told about the learner on each turn (ADR 0009 §4).

Rendered into that call's system prompt only: it travels through the graph in an
untracked channel, so the checkpoint never holds a copy, and a memory the learner
deletes is gone from the very next turn.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UserProfile
from app.memory import service
from app.memory.embedding import MemoryEmbedder

# Character budgets (a rough proxy for tokens) so a long memory list can't crowd out
# the conversation itself.
MAX_FACTS_CHARS = 3000
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

    def is_empty(self) -> bool:
        return not (self.profile or self.facts or self.episodes)


class LearnerSource(Protocol):
    async def load(self, query: str) -> LearnerContext:
        """`query` is the learner's latest message, used to pick related episodes."""
        ...


class DatabaseLearner:
    """LearnerSource over one learner's rows; `conversation_id` is the current one,
    whose own summary is left out (its messages are already in the prompt)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        embedder: MemoryEmbedder | None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._embedder = embedder

    async def load(self, query: str) -> LearnerContext:
        async with self._sessionmaker() as session:
            profile = await service.get_profile(session, self._user_id)
            facts = await service.facts_for_context(session, self._user_id)
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
        )


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
    if shown := facts_shown(context.facts):
        lines = [f"- {fact}" for fact in context.facts[:shown]]
        sections.append("### Things they have told you\n" + "\n".join(lines))
    if context.episodes:
        lines = [f"- {_clip(e, MAX_EPISODE_CHARS)}" for e in context.episodes]
        sections.append("### Earlier conversations\n" + "\n".join(lines))
    return "\n\n".join(sections)


def facts_shown(facts: Sequence[str]) -> int:
    """How many facts fit MAX_FACTS_CHARS. Newest come first, so the oldest are dropped."""
    used = 0
    for count, fact in enumerate(facts):
        used += len(fact)
        if used > MAX_FACTS_CHARS:
            return count
    return len(facts)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
