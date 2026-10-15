"""Messages stamped with when they joined the conversation (task 86.6c, ADR 0044 §5)."""

from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from app.agents.messages import CREATED_AT, add_stamped_messages, created_at
from app.chat.service import to_chat_messages

EARLIER = "2026-10-15T08:00:00+00:00"


def test_new_messages_are_stamped_now() -> None:
    before = datetime.now(UTC)
    merged = add_stamped_messages([], [HumanMessage("Hi", id="u1"), AIMessage("Hello", id="a1")])
    stamps = [created_at(m) for m in merged]
    assert all(s is not None and before <= s <= datetime.now(UTC) for s in stamps)


def test_kept_messages_keep_their_stamp() -> None:
    old = HumanMessage("Hi", id="u1", additional_kwargs={CREATED_AT: EARLIER})
    merged = add_stamped_messages([old], [AIMessage("Hello", id="a1")])
    assert merged[0].additional_kwargs[CREATED_AT] == EARLIER
    assert merged[1].additional_kwargs[CREATED_AT] != EARLIER


def test_a_replaced_message_keeps_the_old_stamp() -> None:
    old = AIMessage("Hel", id="a1", additional_kwargs={CREATED_AT: EARLIER})
    merged = add_stamped_messages([old], [AIMessage("Hello", id="a1")])
    assert [(m.text, m.additional_kwargs[CREATED_AT]) for m in merged] == [("Hello", EARLIER)]


def test_messages_from_before_stamps_get_no_made_up_time() -> None:
    legacy = HumanMessage("Hi", id="u1")
    merged = add_stamped_messages([legacy], [AIMessage("Hello", id="a1")])
    assert created_at(merged[0]) is None
    assert created_at(merged[1]) is not None


def test_removing_still_works() -> None:
    old = HumanMessage("Hi", id="u1", additional_kwargs={CREATED_AT: EARLIER})
    assert add_stamped_messages([old], [RemoveMessage(id="u1")]) == []


def test_history_carries_the_stamp_and_a_joined_reply_its_first_part() -> None:
    later = "2026-10-15T08:00:05+00:00"
    history = to_chat_messages(
        [
            HumanMessage("Quiz me", id="u1", additional_kwargs={CREATED_AT: EARLIER}),
            AIMessage("Sure.", id="a1", additional_kwargs={CREATED_AT: EARLIER}),
            AIMessage("Here it is.", id="a2", additional_kwargs={CREATED_AT: later}),
            HumanMessage("Old one", id="u0"),
        ]
    )
    assert [(m.id, m.created_at) for m in history] == [
        ("u1", datetime.fromisoformat(EARLIER)),
        ("a2", datetime.fromisoformat(EARLIER)),
        ("u0", None),
    ]
