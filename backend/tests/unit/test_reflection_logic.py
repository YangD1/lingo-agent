import uuid

from langchain_core.messages import AIMessage, HumanMessage

from app.memory.reflection import (
    KnownFact,
    ProfileUpdate,
    memory_language,
    profile_changes,
    reflection_input,
    render_messages,
)
from app.memory.worker import split_after


def test_profile_changes_keep_only_clean_values() -> None:
    update = ProfileUpdate(
        native_language="  Chinese ",
        occupation="",
        target_exam="IELTS",
        interests=["hiking", " hiking", "", "jazz"],
        daily_minutes=0,
        explanation_language="en",
    )
    assert profile_changes(update) == {
        "native_language": "Chinese",
        "target_exam": "ielts",
        "interests": ["hiking", "jazz"],
        "explanation_language": "en",
    }
    assert profile_changes(ProfileUpdate(target_exam="toeic")) == {}
    assert profile_changes(None) == {}


def test_cefr_level_is_not_something_reflection_can_set() -> None:
    assert "cefr_level" not in ProfileUpdate.model_fields


def test_input_shows_short_ids_and_both_message_groups() -> None:
    facts = [KnownFact(uuid.uuid4(), "Works as a nurse."), KnownFact(uuid.uuid4(), "Likes jazz.")]
    text = reflection_input(
        profile=None,
        facts=facts,
        earlier=[HumanMessage("Hi"), AIMessage("Hello!")],
        new=[HumanMessage("I moved to Berlin"), AIMessage("How exciting!")],
        language="Simplified Chinese",
    )
    assert "Write facts in: Simplified Chinese" in text
    assert "m1: Works as a nurse.\nm2: Likes jazz." in text
    assert "## Current profile\n(empty)" in text
    assert text.index("Learner: Hi") < text.index("## New messages") < text.index("Berlin")


def test_long_messages_are_cut() -> None:
    rendered = render_messages([HumanMessage("x" * 5000)])
    assert rendered.endswith(" […]") and len(rendered) < 2100


def test_split_after_cursor_or_backlog() -> None:
    messages = [HumanMessage(str(i), id=f"id{i}") for i in range(10)]
    new, earlier = split_after(messages, "id6", backlog=4)
    assert [m.id for m in new] == ["id7", "id8", "id9"] and len(earlier) == 7
    # No cursor, or one that no longer exists: only the recent backlog is new.
    for cursor in (None, "gone"):
        new, earlier = split_after(messages, cursor, backlog=4)
        assert [m.id for m in new] == ["id6", "id7", "id8", "id9"]
    assert split_after(messages, "id9", backlog=4)[0] == []


def test_memory_language_follows_ui_locale() -> None:
    assert memory_language("zh-CN") == "Simplified Chinese"
    assert memory_language("en") == "English"
    assert memory_language(None) == memory_language("fr") == "English"
