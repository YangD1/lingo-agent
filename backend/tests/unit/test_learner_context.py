from datetime import UTC, datetime, timedelta

import pytest

from app.agents.chat_graph import system_prompt
from app.db.models import Conversation, UserProfile
from app.memory import service
from app.memory.context import (
    MAX_EPISODE_CHARS,
    MAX_FACTS_TOKENS,
    LearnerContext,
    estimated_tokens,
    facts_shown,
    profile_lines,
    render_learner_context,
)
from app.memory.language import chat_language
from app.memory.service import SITTING_GAP


def test_nothing_known_renders_nothing() -> None:
    assert render_learner_context(LearnerContext()) == ""
    assert "About this learner" not in system_prompt("")


def test_profile_shows_only_what_is_set() -> None:
    profile = UserProfile(
        occupation="backend developer",
        target_exam="ielts",
        interests=["hiking", "jazz"],
        explanation_language="en",
        manual_fields=[],
    )
    assert profile_lines(profile) == {
        "Occupation": "backend developer",
        "Target exam": "IELTS",
        "Interests": "hiking, jazz",
        "Explain grammar in": "English",
    }


def test_sections_and_budgets() -> None:
    facts = [f"fact {i} " + "x" * 1000 for i in range(10)]
    rendered = render_learner_context(
        LearnerContext(
            profile={"Occupation": "nurse"},
            facts=facts,
            episodes=["y" * (MAX_EPISODE_CHARS * 2)],
        )
    )
    assert "### Profile\n- Occupation: nurse" in rendered
    kept = [f for f in facts if f"- {f}" in rendered]
    # Newest first: a prefix of the list survives, within the budget.
    assert kept == facts[: len(kept)] and 0 < len(kept) < len(facts)
    assert sum(estimated_tokens(f) for f in kept) <= MAX_FACTS_TOKENS
    episode_line = rendered.split("### Earlier conversations\n- ", 1)[1]
    assert len(episode_line) == MAX_EPISODE_CHARS and episode_line.endswith("…")


def test_tokens_are_estimated_per_cjk_character_and_per_4_others() -> None:
    assert estimated_tokens("") == 0
    assert estimated_tokens("Works as a nurse") == 4  # 16 characters
    assert estimated_tokens("下个月有面试。") == 7
    assert estimated_tokens("准备 IELTS") == 4  # 2 + ceil(6 / 4)


def test_chinese_facts_get_a_budget_in_tokens_not_characters() -> None:
    fact = "喜欢先做题再听讲" * 25  # 200 characters, about 200 tokens
    facts = [fact] * 10
    shown = facts_shown(facts)
    # A 3000-character budget kept 15; English facts of this length keep 24.
    assert shown == MAX_FACTS_TOKENS // 200
    assert facts_shown(["x" * 200] * 30) == MAX_FACTS_TOKENS // 50


def test_stable_sections_come_before_progress_and_summaries() -> None:
    rendered = render_learner_context(
        LearnerContext(
            profile={"Occupation": "nurse"},
            facts=["Has an interview next month."],
            episodes=["We practised the past tense."],
            progress="- Grammar course: on lesson 3 of 40",
        )
    )
    order = [
        rendered.index(heading)
        for heading in (
            "### Profile",
            "### Things they have told you",
            "### Where they are now",
            "### Earlier conversations",
        )
    ]
    assert order == sorted(order)


def test_system_prompt_keeps_braces_in_memories() -> None:
    prompt = system_prompt("- Likes {curly} braces")
    assert prompt.startswith("You are a patient")
    assert "## About this learner" in prompt and "- Likes {curly} braces" in prompt


@pytest.mark.parametrize(
    ("chosen", "level", "expected"),
    [
        (None, None, "zh"),  # level not known yet (Q24e)
        (None, "A1", "zh"),
        (None, "A2", "zh"),
        (None, "B1", "en"),
        (None, "C2", "en"),
        ("en", "A1", "en"),  # the learner's own choice wins
        ("zh", "C1", "zh"),
    ],
)
def test_chat_language_by_choice_then_level(
    chosen: str | None, level: str | None, expected: str
) -> None:
    assert chat_language(chosen, level) == expected


def test_system_prompt_says_which_language_to_talk_in() -> None:
    chinese = system_prompt("", language="zh")
    assert "mainly in Chinese" in chinese and "Talk in Simplified Chinese" in chinese
    english = system_prompt("", language="en")
    assert "mainly in English" in english and "Simplified Chinese" not in english
    # Before what it knows about the learner.
    prompt = system_prompt("- Occupation: nurse", language="en")
    assert prompt.index("## Language") < prompt.index("## About this learner")


def test_a_sitting_starts_on_the_first_turn_and_after_a_break() -> None:
    start = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    conversation = Conversation(updated_at=start - timedelta(days=1))
    service.start_sitting(conversation, start)
    assert conversation.sitting_started_at == start  # the first turn

    conversation.updated_at = start + timedelta(minutes=20)
    service.start_sitting(conversation, start + timedelta(minutes=20) + SITTING_GAP / 2)
    assert conversation.sitting_started_at == start  # still going

    back = conversation.updated_at + SITTING_GAP
    service.start_sitting(conversation, back)
    assert conversation.sitting_started_at == back
