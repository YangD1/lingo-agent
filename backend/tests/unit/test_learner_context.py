from app.agents.chat_graph import system_prompt
from app.db.models import UserProfile
from app.memory.context import (
    MAX_EPISODE_CHARS,
    MAX_FACTS_CHARS,
    LearnerContext,
    profile_lines,
    render_learner_context,
)


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
