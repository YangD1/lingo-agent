"""What speaking_coach is told in a speaking conversation (ADR 0029 §2).

Like practice guidance, it goes into that call's system prompt only and is rebuilt
every turn. The scenario comes from `scenarios.yaml`, the learner's level from the
session row, set when the conversation was started.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import Rules, get_rules
from app.db.models import SpeakingSession
from app.prompts import load_prompt
from app.speaking.scenarios import Scenario, get_scenarios

# How speaking_coach opens free talk, which has no scenario to say how.
FREE_OPENING = "Greet the learner warmly and ask how they are or what they'd like to talk about."


@dataclass(frozen=True)
class SpeakingFocus:
    # None: free talk, or a scenario no longer in the file.
    scenario: Scenario | None
    level: CefrLevel
    max_sentences: int


class SpeakingSource(Protocol):
    async def load(self) -> SpeakingFocus: ...


class DatabaseSpeaking:
    """SpeakingSource for one speaking conversation."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        conversation_id: uuid.UUID,
        scenario_id: str | None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._conversation_id = conversation_id
        self._scenario_id = scenario_id

    async def load(self) -> SpeakingFocus:
        rules = get_rules()
        async with self._sessionmaker() as session:
            level = await session.scalar(
                select(SpeakingSession.level).where(
                    SpeakingSession.conversation_id == self._conversation_id
                )
            )
        return focus_for(self._scenario_id, cast(CefrLevel | None, level), rules)


def focus_for(scenario_id: str | None, level: CefrLevel | None, rules: Rules) -> SpeakingFocus:
    level = level or rules.practice.default_level
    scenario = get_scenarios().get(scenario_id) if scenario_id else None
    return SpeakingFocus(scenario, level, rules.speaking.max_sentences[level])


def render_speaking(focus: SpeakingFocus) -> str:
    """The speaking section of the system prompt."""
    # replace, not format: scenario text may contain braces.
    common = {"{level}": focus.level, "{max_sentences}": str(focus.max_sentences)}
    scenario = focus.scenario
    if scenario is None:
        return _fill(load_prompt("speaking_free"), common)
    expressions = ""
    if scenario.target_expressions:
        listed = "\n".join(f"  - {e}" for e in scenario.target_expressions)
        expressions = (
            "- Expressions the learner could try (give them chances to use these; don't "
            f"recite them):\n{listed}"
        )
    return _fill(
        load_prompt("speaking_scenario"),
        common
        | {
            "{role}": scenario.role,
            "{goal}": scenario.learner_goal_en,
            "{expressions}": expressions,
        },
    ).strip()


def opening_cue(focus: SpeakingFocus) -> str:
    """What speaking_coach is told when it speaks first (Q58e)."""
    opening = focus.scenario.opening if focus.scenario else FREE_OPENING
    return load_prompt("speaking_opening").replace("{opening}", opening)


def _fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace(key, value)
    return template
