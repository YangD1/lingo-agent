"""Which coach answers a turn (ADR 0023 §3).

The route comes first from what is certain about the conversation, without a model
call: a practice conversation (it has a grammar point) goes to grammar_coach, one
opened from an article ("ask the tutor" on the reading page, Q43h) to reading_coach,
a speaking one to speaking_coach (ADR 0029 §2), planning and daily conversations to
the tutor. Free chat starts with the tutor too; the supervisor may then hand a turn
to writing_coach (task 38.4): a message long enough to be a piece of writing (Q38a) is
classified by the `route` task, and anything short of a clear answer leaves it with the
tutor. The classifier never picks reading_coach or speaking_coach: without an article
or a speaking conversation they have nothing to do.
"""

import asyncio
import logging
from enum import StrEnum
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_structured_llm
from app.writing.text import word_count

logger = logging.getLogger(__name__)

TASK = "route"
# Q38a: shorter messages stay with the tutor without a call; a piece of writing worth
# reviewing is longer than a chat message.
MIN_WORDS_TO_CLASSIFY = 60
# The tutor's reply is held up while this runs; past it, the tutor answers.
TIMEOUT_SECONDS = 8
# How much of the tutor's previous message the classifier sees (it may have asked for
# the writing).
PREVIOUS_CHARS = 600


class Route(StrEnum):
    TUTOR = "tutor"
    GRAMMAR_COACH = "grammar_coach"
    WRITING_COACH = "writing_coach"
    READING_COACH = "reading_coach"
    SPEAKING_COACH = "speaking_coach"


def route_for(
    focus_kc_id: str | None, article_id: int | None = None, *, speaking: bool = False
) -> Route:
    """The coach of a conversation, from its purpose, grammar point or article (planning
    and daily conversations are the tutor's, with their brief and limited tools). A
    reading conversation whose article was deleted goes back to the tutor."""
    if speaking:
        return Route.SPEAKING_COACH
    if focus_kc_id is not None:
        return Route.GRAMMAR_COACH
    return Route.READING_COACH if article_id is not None else Route.TUTOR


class RouteDecision(BaseModel):
    """The `route` task's answer: who replies to the learner's message."""

    route: Literal["tutor", "writing_coach"] = Field(
        description="writing_coach when the learner shares a piece of their own English "
        "writing to be reviewed or corrected; tutor for everything else."
    )


def worth_classifying(text: str) -> bool:
    """Q38a: only a message with enough English words may be a piece of writing."""
    return word_count(text) >= MIN_WORDS_TO_CLASSIFY


async def classify(
    ctx: TenantProviderContext, text: str, previous: str, config: RunnableConfig
) -> Route:
    """The coach for one free-chat message. Never raises: a missing model, a failed or
    slow call all leave the turn with the tutor."""
    prompt = f"## Learner's message\n{text}"
    if previous:
        prompt = f"## Tutor's previous message\n{previous[-PREVIOUS_CHARS:]}\n\n{prompt}"
    try:
        llm = get_structured_llm(ctx, TASK, RouteDecision)
        async with asyncio.timeout(TIMEOUT_SECONDS):
            decision = await llm.ainvoke(
                [SystemMessage(load_prompt(TASK)), HumanMessage(prompt)], config=config
            )
        # Inside the try: a reply without the tool call parses to None.
        return Route(decision.route)
    except Exception:
        logger.warning("route classification failed; the tutor answers", exc_info=True)
        return Route.TUTOR
