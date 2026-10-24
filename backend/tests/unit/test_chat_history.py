"""`to_chat_messages` on a realtime call's lines (task 62.5)."""

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.deepen import SEGMENT_KEY
from app.chat.service import REPLY_PART_SEPARATOR, to_chat_messages
from app.realtime.transcript import INTERRUPTED, VOICE_CALL

VOICE = {VOICE_CALL: True}


def test_call_replies_in_a_row_stay_apart() -> None:
    # The learner's turn in between had no transcript: two replies, not one.
    messages = to_chat_messages(
        [
            AIMessage("Hi! How was your day?", id="t1", additional_kwargs=VOICE),
            AIMessage("Still there?", id="t2", additional_kwargs=VOICE),
            HumanMessage("Yes, sorry", id="l1", additional_kwargs=VOICE),
        ]
    )
    assert [(m.id, m.content) for m in messages] == [
        ("t1", "Hi! How was your day?"),
        ("t2", "Still there?"),
        ("l1", "Yes, sorry"),
    ]


def test_a_cut_short_reply_is_marked() -> None:
    messages = to_chat_messages(
        [
            AIMessage("Let me tell you", id="t1", additional_kwargs=VOICE | {INTERRUPTED: True}),
            HumanMessage("Wait", id="l1", additional_kwargs=VOICE),
            AIMessage("Sure", id="t2", additional_kwargs=VOICE),
        ]
    )
    assert [m.interrupted for m in messages] == [True, False, False]


def test_chat_reply_parts_still_join() -> None:
    messages = to_chat_messages(
        [
            HumanMessage("hi", id="u1"),
            AIMessage("Part one", id="a1"),
            AIMessage("Part two", id="a2", additional_kwargs={INTERRUPTED: True}),
        ]
    )
    assert [(m.id, m.content, m.interrupted) for m in messages] == [
        ("u1", "hi", False),
        ("a2", f"Part one{REPLY_PART_SEPARATOR}Part two", False),
    ]


def test_follow_up_offsets_count_utf16_units() -> None:
    # The page slices `content` with JavaScript indexes: an emoji there is two units.
    messages = to_chat_messages(
        [
            HumanMessage("Why?", id="l1"),
            AIMessage("Good question 👍", id="t1"),
            AIMessage("Because.", id="t2", additional_kwargs={SEGMENT_KEY: 1}),
        ]
    )
    (reply,) = [m for m in messages if m.role == "assistant"]
    assert reply.content == "Good question 👍\n\nBecause."
    (follow_up,) = reply.follow_ups
    assert (follow_up.index, follow_up.outcome) == (1, "done")
    assert follow_up.offset == len("Good question ") + 2 + 2
