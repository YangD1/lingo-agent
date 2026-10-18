"""load_skill's reading and the graph's bookkeeping for it (ADR 0055 §6)."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.chat_graph import (
    MAX_SKILL_ROUNDS,
    skills_read_earlier,
    system_prompt,
    tool_rounds,
)
from app.prompts import load_prompt
from app.skills import get_skills
from app.skills.tool import read_skill, skills_section

SKILL = "exercise-writing"


def skill_round(i: int, name: str = "load_skill") -> list[AIMessage | ToolMessage]:
    call = {"name": name, "args": {"name": SKILL, "part": f"p{i}"}, "id": f"c{i}"}
    return [AIMessage("", tool_calls=[call]), ToolMessage("x", tool_call_id=f"c{i}", name=name)]


def test_read_skill_gives_the_text_and_its_parts() -> None:
    outcome = read_skill({"name": SKILL}, ())
    assert outcome.ok and outcome.read == (SKILL, None)
    assert "Parts with details" in outcome.content and "find-fix" in outcome.content

    part = read_skill({"name": SKILL, "part": "transform"}, ())
    assert part.read == (SKILL, "transform")
    assert "Parts with details" not in part.content


def test_read_skill_refuses_repeats_and_bad_arguments() -> None:
    again = read_skill({"name": SKILL}, {(SKILL, None)})
    assert again.ok and again.read is None and "already read" in again.content
    # An empty part is the skill itself.
    assert read_skill({"name": SKILL, "part": ""}, {(SKILL, None)}).read is None
    for args in ({}, {"name": SKILL, "user_id": "u1"}, {"name": 3}):
        bad = read_skill(args, ())
        assert not bad.ok and bad.read is None


def test_skill_rounds_are_free_up_to_their_limit() -> None:
    human = HumanMessage("hi", id="u1")
    skills = [m for i in range(MAX_SKILL_ROUNDS + 1) for m in skill_round(i)]
    assert tool_rounds([human, *skills[: 2 * MAX_SKILL_ROUNDS]]) == 0
    assert tool_rounds([human, *skills]) == 1
    # A round with a card tool counts, even with a skill read in it.
    mixed = AIMessage(
        "",
        tool_calls=[
            {"name": "load_skill", "args": {"name": SKILL}, "id": "m1"},
            {"name": "give_quiz", "args": {}, "id": "m2"},
        ],
    )
    assert tool_rounds([human, mixed]) == 1


def test_only_earlier_turns_lose_their_skill_text() -> None:
    earlier = skill_round(1)
    failed = [
        AIMessage("", tool_calls=[{"name": "load_skill", "args": {"name": "x"}, "id": "f"}]),
        ToolMessage("Error", tool_call_id="f", name="load_skill", status="error"),
    ]
    current = skill_round(2)
    messages = [
        HumanMessage("a", id="u1"),
        *earlier,
        *failed,
        AIMessage("ok"),
        HumanMessage("b", id="u2"),
        *current,
    ]
    out = skills_read_earlier(messages)
    assert out[2].text.startswith(f"Read {SKILL} (p1) in an earlier turn")
    assert out[4].text == "Error"
    assert out[-1].text == "x"
    assert messages[2].text == "x"  # the input is left as it was


def test_the_skills_section_sits_in_the_stable_start_of_the_prompt() -> None:
    section = skills_section()
    assert f"- {SKILL}: {get_skills()[SKILL].description}" in section
    prompt = system_prompt("- Likes tea", "practice", "tools", language="en", skills=section)
    language = prompt.index(load_prompt("language_en"))
    assert language < prompt.index("## Skills") < prompt.index("Likes tea")
    assert "## Skills" not in system_prompt("- Likes tea")
