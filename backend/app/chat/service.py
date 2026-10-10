"""Conversation CRUD. Messages live in the LangGraph checkpoint, not in our tables."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import GrammarKC
from app.agents.chat_graph import ChatGraph
from app.db.models import Article, Attachment, Conversation
from app.services.vocab.scheduler import day_bounds


class ConversationNotFoundError(Exception):
    """Missing *or* owned by someone else: callers must not tell the two apart."""


@dataclass(frozen=True)
class ChatMessage:
    id: str | None
    role: Literal["user", "assistant"]
    content: str


_ROLES: dict[str, Literal["user", "assistant"]] = {"human": "user", "ai": "assistant"}


def thread_config(conversation_id: uuid.UUID) -> RunnableConfig:
    """LangGraph thread_id is the conversation id."""
    return {"configurable": {"thread_id": str(conversation_id)}}


async def list_conversations(session: AsyncSession, user_id: uuid.UUID) -> list[Conversation]:
    rows = await session.scalars(
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            # Speaking conversations live on the speaking page (Q58g).
            Conversation.purpose.is_distinct_from("speaking"),
            Conversation.purpose.is_distinct_from("realtime"),
        )
        .order_by(Conversation.updated_at.desc(), Conversation.id)
    )
    return list(rows)


async def create_conversation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    focus: GrammarKC | None = None,
    purpose: str | None = None,
    article: Article | None = None,
    locale: str | None = None,
) -> Conversation:
    """A free chat; with `focus` a practice conversation on that grammar point; with
    `purpose` "planning" a study-planning one; with `article` one about that article
    (Q43h). Titled in the UI's `locale` (the list shows titles as they are). Daily
    conversations come from `todays_daily`."""
    conversation = Conversation(tenant_id=tenant_id, user_id=user_id, purpose=purpose)
    if article is not None:
        conversation.purpose = "reading"
        conversation.article_id = article.id
        conversation.title = reading_title(article.title, locale)
    elif focus is not None:
        conversation.focus_kc_id = focus.id
        conversation.title = practice_title(focus, locale)
    elif purpose == "planning":
        conversation.title = planning_title(locale)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


def practice_title(kc: GrammarKC, locale: str | None) -> str:
    if locale and locale.lower().startswith("zh"):
        return f"练习：{kc.name_zh}"  # noqa: RUF001 (Chinese punctuation)
    return f"Practice: {kc.name_en}"


def reading_title(title: str, locale: str | None) -> str:
    title = title if len(title) <= 80 else title[:79] + "\u2026"
    if locale and locale.lower().startswith("zh"):
        return f"阅读：{title}"  # noqa: RUF001 (Chinese punctuation)
    return f"Reading: {title}"


def planning_title(locale: str | None) -> str:
    if locale and locale.lower().startswith("zh"):
        return "学习规划"
    return "Study plan"


def daily_title(day: date, locale: str | None) -> str:
    if locale and locale.lower().startswith("zh"):
        return f"今天的学习 · {day.month}月{day.day}日"
    return f"Today's study · {day:%b} {day.day}"


async def daily_conversation(
    session: AsyncSession, user_id: uuid.UUID, tz: ZoneInfo
) -> Conversation | None:
    """The learner's daily conversation for today in `tz` (ADR 0016 §1), if any."""
    start, end = day_bounds(datetime.now(UTC), tz)
    return await session.scalar(
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.purpose == "daily",
            Conversation.created_at >= start,
            Conversation.created_at < end,
        )
        .order_by(Conversation.created_at.desc(), Conversation.id)
        .limit(1)
    )


async def todays_daily(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    tz: ZoneInfo,
    *,
    locale: str | None = None,
) -> tuple[Conversation, bool]:
    """Today's daily conversation, created if there is none yet; True if created.

    Serialised per learner with a transaction-scoped advisory lock, so two first
    messages sent at once share one conversation.
    """
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"daily:{user_id}"))))
    existing = await daily_conversation(session, user_id, tz)
    if existing is not None:
        await session.commit()  # releases the lock
        return existing, False
    conversation = Conversation(
        tenant_id=tenant_id,
        user_id=user_id,
        purpose="daily",
        title=daily_title(datetime.now(UTC).astimezone(tz).date(), locale),
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation, True


async def unstarted_planning(
    session: AsyncSession, graph: ChatGraph, user_id: uuid.UUID
) -> Conversation | None:
    """The learner's latest planning conversation if nothing is in it yet, not even the
    tutor's opening (which would sum up an older result): pressing the button twice
    leaves one conversation."""
    latest = await session.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.purpose == "planning")
        .order_by(Conversation.created_at.desc(), Conversation.id)
        .limit(1)
    )
    if latest is None or await get_history(graph, latest):
        return None
    return latest


async def unstarted_practice(
    session: AsyncSession, graph: ChatGraph, user_id: uuid.UUID, kc_id: str
) -> Conversation | None:
    """The learner's latest practice conversation on `kc_id`, if they haven't said
    anything in it yet (the tutor's opening may be there): opening the same practice
    again returns to it instead of leaving empty conversations behind (Q19c)."""
    return await _unstarted(session, graph, user_id, Conversation.focus_kc_id == kc_id)


async def unstarted_reading(
    session: AsyncSession, graph: ChatGraph, user_id: uuid.UUID, article_id: int
) -> Conversation | None:
    """Likewise for asking the tutor about an article again (Q43h)."""
    return await _unstarted(session, graph, user_id, Conversation.article_id == article_id)


async def _unstarted(
    session: AsyncSession,
    graph: ChatGraph,
    user_id: uuid.UUID,
    which: ColumnElement[bool],
) -> Conversation | None:
    latest = await session.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id, which)
        .order_by(Conversation.created_at.desc(), Conversation.id)
        .limit(1)
    )
    if latest is None:
        return None
    history = await get_history(graph, latest)
    return None if any(m.role == "user" for m in history) else latest


async def get_owned_conversation(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise ConversationNotFoundError
    return conversation


# Between the texts of one turn's tutor messages (a reply around tool calls).
REPLY_PART_SEPARATOR = "\n\n"


def to_chat_messages(messages: list[BaseMessage]) -> list[ChatMessage]:
    """User-visible turns only (system/tool messages are internal).

    A turn with tool calls has several tutor messages (ADR 0015 §5); they show as one,
    under the last one's id, with the calls themselves left out.
    """
    out: list[ChatMessage] = []
    for m in messages:
        if m.type not in _ROLES:
            continue
        role = _ROLES[m.type]
        if role == "assistant" and out and out[-1].role == "assistant":
            parts = [p for p in (out[-1].content, m.text) if p]
            out[-1] = ChatMessage(id=m.id, role=role, content=REPLY_PART_SEPARATOR.join(parts))
            continue
        out.append(ChatMessage(id=m.id, role=role, content=m.text))
    return out


async def get_history(graph: ChatGraph, conversation: Conversation) -> list[ChatMessage]:
    state = await graph.aget_state(thread_config(conversation.id))
    return to_chat_messages(state.values.get("messages", []))


async def attachments_by_message(
    session: AsyncSession, conversation: Conversation, history: list[ChatMessage]
) -> dict[str, list[Attachment]]:
    """Sent attachments of the learner's messages, keyed by message id."""
    ids = [m.id for m in history if m.role == "user" and m.id]
    if not ids:
        return {}
    rows = await session.scalars(
        select(Attachment)
        .where(Attachment.conversation_id == conversation.id, Attachment.message_id.in_(ids))
        .order_by(Attachment.created_at, Attachment.id)
    )
    found: dict[str, list[Attachment]] = {}
    for row in rows:
        found.setdefault(row.message_id or "", []).append(row)
    return found


async def delete_conversation(
    session: AsyncSession, checkpointer: BaseCheckpointSaver[str], conversation: Conversation
) -> None:
    # Checkpoints first: if that fails the row survives and the user can retry, instead
    # of leaving an orphaned thread nobody can reach or delete.
    await checkpointer.adelete_thread(str(conversation.id))
    await session.delete(conversation)
    await session.commit()
