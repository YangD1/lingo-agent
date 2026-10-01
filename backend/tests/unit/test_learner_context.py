import pytest

from app.agents.chat_graph import system_prompt
from app.db.models import UserProfile
from app.memory.context import (
    MAX_EPISODE_CHARS,
    MAX_FACTS_CHARS,
    LearnerContext,
    profile_lines,
    render_learner_context,
)
from app.memory.language import chat_language


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
    assert sum(len(f) for f in kept) <= MAX_FACTS_CHARS
    episode_line = rendered.split("### Earlier conversations\n- ", 1)[1]
    assert len(episode_line) == MAX_EPISODE_CHARS and episode_line.endswith("…")


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
