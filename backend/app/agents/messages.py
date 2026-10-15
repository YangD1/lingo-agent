"""The chat history's messages, each stamped with when it joined the conversation.

LangChain messages carry no time, and a test-out quiz card hangs under no message
(ADR 0044 §5): to place it among them, the messages need one. The stamp goes in
`additional_kwargs`, which none of the model clients send on (they read named keys only).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, TypedDict, cast

from langchain_core.messages import AnyMessage, BaseMessage
from langgraph.graph.message import Messages, add_messages

CREATED_AT = "created_at"


def add_stamped_messages(left: Messages, right: Messages) -> Sequence[BaseMessage]:
    """`add_messages`, stamping the messages new to the history with the current time.

    A message replacing one by id keeps the old one's stamp; messages saved before stamps
    existed stay without one rather than getting a wrong time.
    """
    # add_messages always returns messages; its annotation is the input union.
    merged = cast(list[BaseMessage], add_messages(left, right))
    before = {m.id: m for m in cast(list[BaseMessage], add_messages(left, []))}
    now = datetime.now(UTC).isoformat()
    for message in merged:
        if CREATED_AT in message.additional_kwargs:
            continue
        old = before.get(message.id)
        if old is None:
            message.additional_kwargs[CREATED_AT] = now
        elif CREATED_AT in old.additional_kwargs:
            message.additional_kwargs[CREATED_AT] = old.additional_kwargs[CREATED_AT]
    return merged


def created_at(message: BaseMessage) -> datetime | None:
    stamp = message.additional_kwargs.get(CREATED_AT)
    return datetime.fromisoformat(stamp) if isinstance(stamp, str) else None


class StampedMessagesState(TypedDict):
    """`MessagesState` with stamped messages."""

    messages: Annotated[list[AnyMessage], add_stamped_messages]
