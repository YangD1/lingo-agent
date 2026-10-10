"""Speaking sessions (ADR 0029 §5): starting one, counting its turns, ending it with a
summary.

A session is one speaking conversation (`purpose = speaking`). Ending it makes one
`speaking_summary` call over the conversation; a session left idle is ended the next
time the learner opens the speaking page or the conversation (Q58c), never in the
background.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.elo import update_ability
from app.adaptive.kc.catalog import CEFR_LEVELS, CefrLevel
from app.adaptive.rules import Intelligibility, Rules, get_rules
from app.agents.chat_graph import ChatGraph
from app.agents.exercise_graph import StructuredCall
from app.chat.service import thread_config
from app.db.models import Conversation, SpeakingSession, UserProfile
from app.services.speech.shadowing import speaking_ability
from app.speaking import summary
from app.speaking.scenarios import Scenario, get_scenarios, rank

logger = logging.getLogger(__name__)

# A spoken turn's length when the transcription didn't say: about 150 words a minute.
WORDS_PER_SECOND = 2.5


class UnknownScenarioError(ValueError):
    pass


async def start(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    scenario_id: str | None,
    *,
    locale: str | None = None,
) -> SpeakingSession:
    """A new speaking conversation and its session, at the learner's level; commits.
    Raises `UnknownScenarioError` for an id not in the scenario file."""
    scenario = None
    if scenario_id is not None and (scenario := get_scenarios().get(scenario_id)) is None:
        raise UnknownScenarioError(scenario_id)
    rules = get_rules()
    level = await session.scalar(
        select(UserProfile.cefr_level).where(UserProfile.user_id == user_id)
    )
    conversation = Conversation(
        tenant_id=tenant_id,
        user_id=user_id,
        purpose="speaking",
        scenario_id=scenario_id,
        title=speaking_title(scenario, locale),
    )
    session.add(conversation)
    await session.flush()
    row = SpeakingSession(
        user_id=user_id,
        conversation_id=conversation.id,
        scenario_id=scenario_id,
        level=level or rules.practice.default_level,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def speaking_title(scenario: Scenario | None, locale: str | None) -> str:
    if locale and locale.lower().startswith("zh"):
        return f"口语：{scenario.title_zh if scenario else '自由聊'}"  # noqa: RUF001
    return f"Speaking: {scenario.title_en if scenario else 'Free talk'}"


async def record_turn(
    session: AsyncSession, conversation_id: uuid.UUID, text: str, spoken_seconds: float | None
) -> None:
    """Count one learner turn: `spoken_seconds` is None for a typed one; 0 for a spoken
    one whose transcription gave no duration estimates it from its words. Does not
    commit."""
    spoken = spoken_seconds is not None
    seconds = spoken_seconds or (len(text.split()) / WORDS_PER_SECOND if spoken else 0.0)
    await session.execute(
        update(SpeakingSession)
        .where(SpeakingSession.conversation_id == conversation_id)
        .values(
            turns=SpeakingSession.turns + 1,
            spoken_turns=SpeakingSession.spoken_turns + int(spoken),
            spoken_seconds=SpeakingSession.spoken_seconds + seconds,
        )
    )


async def idle_sessions(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, rules: Rules
) -> list[uuid.UUID]:
    """The learner's active sessions with no turn for `idle_minutes` (Q58c)."""
    cutoff = now - timedelta(minutes=rules.speaking.idle_minutes)
    rows = await session.scalars(
        select(SpeakingSession.id)
        .join(Conversation, Conversation.id == SpeakingSession.conversation_id)
        .where(
            SpeakingSession.user_id == user_id,
            SpeakingSession.status == "active",
            Conversation.updated_at < cutoff,
        )
    )
    return list(rows)


async def end(
    maker: async_sessionmaker[AsyncSession],
    graph: ChatGraph,
    session_id: uuid.UUID,
    call: StructuredCall,
) -> SpeakingSession | None:
    """End the session and sum it up; commits. A session already done is left as it
    is; a failed one is tried again. A failed call leaves it `failed`, with the error
    logged. None when the session is gone. The caller holds the conversation's lock."""
    rules = get_rules()
    async with maker() as session:
        row = await session.get(SpeakingSession, session_id)
        if row is None or row.status == "done":
            return row
        conversation_id, user_id = row.conversation_id, row.user_id
        explain_in = await session.scalar(
            select(UserProfile.explanation_language).where(UserProfile.user_id == user_id)
        )
        scenario = get_scenarios().get(row.scenario_id) if row.scenario_id else None
        level = cast(CefrLevel, row.level)
    state = await graph.aget_state(thread_config(conversation_id))
    messages: list[BaseMessage] = [
        m
        for m in state.values.get("messages", [])
        if isinstance(m, HumanMessage) or (isinstance(m, AIMessage) and m.text)
    ]
    learner_texts = [m.text for m in messages if isinstance(m, HumanMessage)]

    stored: dict[str, Any] | None = None
    status = "done"
    if learner_texts:  # nothing said, nothing to sum up
        try:
            reply = await call(
                summary.summary_messages(
                    messages,
                    scenario=scenario,
                    level=level,
                    explain_in="en" if explain_in == "en" else "zh",
                ),
                summary.SpeakingSummary,
            )
            stored = summary.check(cast(summary.SpeakingSummary, reply.output), learner_texts)
        except Exception:
            logger.exception("summarising speaking session %s failed", session_id)
            status = "failed"

    async with maker() as session:
        row = await session.get(SpeakingSession, session_id, with_for_update=True)
        if row is None or row.status == "done":
            return row
        row.status = status
        row.ended_at = row.ended_at or datetime.now(UTC)
        if stored is not None:
            row.summary = stored
            row.intelligibility = cast(str, stored["intelligibility"])
            await _move_ability(session, row, scenario, rules)
        await session.commit()
        await session.refresh(row)
        return row


async def _move_ability(
    session: AsyncSession, row: SpeakingSession, scenario: Scenario | None, rules: Rules
) -> None:
    """One Elo step on speaking ability from the intelligibility rating (Q58d), once,
    and only after enough spoken turns."""
    if row.counted or row.intelligibility is None:
        return
    if row.spoken_turns < rules.speaking.min_spoken_turns:
        return
    level = scenario_level(cast(CefrLevel, row.level), scenario)
    ability = await speaking_ability(session, row.user_id, rules)
    ability.rating = update_ability(
        ability.rating,
        rules.difficulty.cefr_anchor[level],
        rules.speaking.intelligibility_outcome[cast(Intelligibility, row.intelligibility)],
        ability.attempts,
        rules,
        0.0,
    )
    ability.attempts += 1
    row.counted = True


def scenario_level(level: CefrLevel, scenario: Scenario | None) -> CefrLevel:
    """The session's difficulty: the learner's level kept within the scenario's range."""
    if scenario is None:
        return level
    low, high = (rank(lv) for lv in scenario.levels)
    return CEFR_LEVELS[min(max(rank(level), low), high)]
