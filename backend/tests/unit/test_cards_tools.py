import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agents.chat_graph import tool_rounds
from app.cards.tools import TOOL_NAMES, TOOL_SCHEMAS, CardScope, ToolCallError, draft_card
from app.chat.service import to_chat_messages

KC = "g.word_order_svo"


def test_tool_schemas_carry_no_ids_and_list_the_books() -> None:
    schemas = {
        s["function"]["name"]: s["function"] for s in map(convert_to_openai_tool, TOOL_SCHEMAS)
    }
    assert set(schemas) == TOOL_NAMES
    for schema in schemas.values():
        # Identity comes from the runtime, never from the model (ADR 0013 §1).
        assert not {"user_id", "conversation_id", "turn_id"} & set(
            schema["parameters"]["properties"]
        )
    book = schemas["propose_word_book"]["parameters"]["properties"]["book_id"]
    assert {"cet4", "ielts", "oxford3000"} <= set(book["enum"])


def test_word_book_proposals() -> None:
    draft = draft_card("propose_word_book", {"book_id": "cet4"})
    assert (draft.kind, draft.params, draft.has_effect) == (
        "word_book",
        {"book_id": "cet4", "daily_new": None},
        True,
    )
    with pytest.raises(ToolCallError, match="unknown book_id 'nope'"):
        draft_card("propose_word_book", {"book_id": "nope"})
    with pytest.raises(ToolCallError, match="daily_new"):
        draft_card("propose_word_book", {"book_id": "cet4", "daily_new": 500})
    with pytest.raises(ToolCallError, match="user_id"):
        draft_card("propose_word_book", {"book_id": "cet4", "user_id": "someone"})


def test_goal_proposals_keep_only_what_was_given() -> None:
    draft = draft_card("propose_learning_goal", {"goal": "  pass IELTS  ", "daily_minutes": 20})
    assert draft.params == {"goal": "pass IELTS", "daily_minutes": 20}
    with pytest.raises(ToolCallError, match="at least one"):
        draft_card("propose_learning_goal", {"goal": "   "})
    with pytest.raises(ToolCallError, match="unknown target_exam"):
        draft_card("propose_learning_goal", {"target_exam": "toeic"})


def test_suggestions_and_their_scope() -> None:
    assert draft_card("suggest_practice", {"kc_id": KC}).params == {"kc_id": KC}
    assert not draft_card("suggest_link", {"kind": "placement"}).has_effect
    with pytest.raises(ToolCallError, match="unknown kc_id"):
        draft_card("suggest_practice", {"kc_id": "g.made_up"})
    scope = CardScope(kc_ids={"g.other"}, links={"vocab_review"})
    with pytest.raises(ToolCallError, match="not among"):
        draft_card("suggest_practice", {"kc_id": KC}, scope)
    with pytest.raises(ToolCallError, match="not among"):
        draft_card("suggest_link", {"kind": "placement"}, scope)
    with pytest.raises(ToolCallError, match="unknown tool"):
        draft_card("delete_everything", {})


def turn_with_tools() -> list:  # type: ignore[type-arg]
    call = {"name": "suggest_link", "args": {"kind": "placement"}, "id": "c1"}
    return [
        HumanMessage("hi", id="u1"),
        AIMessage("Let me see.", id="a1", tool_calls=[call]),
        ToolMessage("Card shown", tool_call_id="c1", id="t1"),
        AIMessage("", id="a2", tool_calls=[{**call, "id": "c2"}]),
        ToolMessage("Card shown", tool_call_id="c2", id="t2"),
        AIMessage("Here you go.", id="a3"),
    ]


def test_history_shows_a_turn_with_tools_as_one_reply() -> None:
    messages = to_chat_messages(turn_with_tools())
    assert [(m.id, m.role, m.content) for m in messages] == [
        ("u1", "user", "hi"),
        ("a3", "assistant", "Let me see.\n\nHere you go."),
    ]


def test_tool_rounds_count_since_the_learner_last_wrote() -> None:
    messages = turn_with_tools()
    assert tool_rounds(messages[:1]) == 0
    assert tool_rounds(messages[:3]) == 1
    assert tool_rounds(messages) == 2
    assert tool_rounds([*messages, HumanMessage("thanks", id="u2")]) == 0
