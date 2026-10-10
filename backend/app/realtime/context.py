"""What the tutor is told when a realtime call opens (ADR 0030 §3): the call's ground
rules (`prompts/realtime_tutor.md`, the same recast-only way as speaking_coach, ADR 0029
§2), the scenario or free talk at the learner's level, and what is known about the
learner. Given once, as the session's instructions; nothing is looked up mid-call.

Memories (Q60e): with a scenario, the earlier conversations most related to it; in free
talk there is nothing to match against, so only the profile and the facts.
"""

import uuid
from dataclasses import replace
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import get_rules
from app.chat.speaking import FREE_OPENING, SpeakingFocus, render_speaking
from app.db.models import UserProfile
from app.memory.context import DatabaseLearner, render_learner_context
from app.memory.embedding import MemoryEmbedder
from app.prompts import load_prompt
from app.speaking.scenarios import Scenario


async def call_instructions(
    maker: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    scenario: Scenario | None,
    embedder: MemoryEmbedder | None,
) -> str:
    rules = get_rules()
    async with maker() as session:
        level = await session.scalar(
            select(UserProfile.cefr_level).where(UserProfile.user_id == user_id)
        )
    level = cast(CefrLevel, level or rules.practice.default_level)
    focus = SpeakingFocus(scenario, level, rules.speaking.max_sentences[level])

    query = f"{scenario.title_en}. {scenario.learner_goal_en}" if scenario else ""
    learner = await DatabaseLearner(maker, user_id, None, embedder if scenario else None).load(
        query
    )
    if scenario is None:
        learner = replace(learner, episodes=(), episode_ids=())

    opening = scenario.opening if scenario else FREE_OPENING
    parts = [
        load_prompt("realtime_tutor").replace("{opening}", opening).strip(),
        render_speaking(focus),
    ]
    if rendered := render_learner_context(learner):
        parts.append(load_prompt("learner_context").replace("{learner_context}", rendered).strip())
    return "\n\n".join(parts)
