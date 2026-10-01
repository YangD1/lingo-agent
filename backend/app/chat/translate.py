"""A tutor message in the other language, on the learner's request (ADR 0017 §4).

Kept in `message_translations`, so switching back and forth calls no model.
"""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chat_graph import ChatGraph
from app.chat.service import get_history
from app.db.models import Conversation, MessageTranslation
from app.prompts import load_prompt
from app.providers.config import TenantProviderContext
from app.providers.llm import get_structured_llm

TASK = "translate"

type Target = Literal["zh", "en"]
_LANGUAGES: dict[Target, str] = {"zh": "Simplified Chinese", "en": "English"}


class Translation(BaseModel):
    text: str = Field(description="The whole message, translated")


class MessageNotFoundError(Exception):
    """No tutor message with that id in the conversation."""


async def cached(
    session: AsyncSession, conversation: Conversation, message_id: str, target: Target
) -> str | None:
    return await session.scalar(
        select(MessageTranslation.text).where(
            MessageTranslation.conversation_id == conversation.id,
            MessageTranslation.message_id == message_id,
            MessageTranslation.target == target,
        )
    )


async def translate(
    session: AsyncSession,
    graph: ChatGraph,
    ctx: TenantProviderContext,
    conversation: Conversation,
    message_id: str,
    target: Target,
    config: RunnableConfig,
) -> str:
    """The stored translation, or a new one (raises MessageNotFoundError,
    NoModelConfiguredError, or the provider's error)."""
    found = await cached(session, conversation, message_id, target)
    if found is not None:
        return found
    history = await get_history(graph, conversation)
    message = next((m for m in history if m.id == message_id and m.role == "assistant"), None)
    if message is None or not message.content.strip():
        raise MessageNotFoundError
    llm = get_structured_llm(ctx, TASK, Translation)
    prompt = f"Target language: {_LANGUAGES[target]}\n\n## Message\n{message.content}"
    result = await llm.ainvoke(
        [SystemMessage(load_prompt(TASK)), HumanMessage(prompt)], config=config
    )
    text = result.text.strip()
    await session.execute(
        insert(MessageTranslation)
        .values(conversation_id=conversation.id, message_id=message_id, target=target, text=text)
        .on_conflict_do_nothing()
    )
    await session.commit()
    return await cached(session, conversation, message_id, target) or text
