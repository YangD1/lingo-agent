"""load_skill in a conversation (ADR 0055 §6): counted apart from the card tools, each
skill read once a turn, and kept out of later turns."""

from typing import Any

from httpx import AsyncClient
from langchain_core.messages import BaseMessage, ToolMessage

from app.agents.chat_graph import MAX_SKILL_ROUNDS, MAX_TOOL_ROUNDS
from app.skills import get_skills
from tests.integration.test_chat_send import send
from tests.integration.test_chat_tools import (
    Script,
    _clear_caches,  # noqa: F401
    activity,
    cards,
    kinds,
    ready,
    system_text,
    tool_call,
)
from tests.integration.test_chat_tools import script as tool_script

script = tool_script

SKILL = "exercise-writing"


def load(part: str | None = None, name: str = SKILL) -> dict[str, Any]:
    # Built here: tool_call's own first parameter is called `name`.
    args = {"name": name, **({"part": part} if part else {})}
    return {**tool_call("load_skill"), "args": args}


def results(messages: list[BaseMessage]) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage)]


async def test_reading_a_skill_costs_no_tool_round(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    call = load()
    script.replies = [
        [call],
        [tool_call("suggest_link", kind="vocab_review")],
        [tool_call("suggest_link", kind="placement")],
        "Try this: ...",
    ]

    _, events, _ = await send(client, conversation, "Give me a question on the past tense")

    # The skill round is free: both card rounds still had tools.
    assert [offered is not None for offered, _ in script.calls] == [True, True, True, False]
    (read,) = results(script.calls[1][1])
    assert read.status == "success"
    assert read.text.startswith(f'<skill name="{SKILL}">')
    assert get_skills()[SKILL].body in read.text
    assert "cloze" in read.text  # the parts it can read next
    # The skill shows no card; the two links do.
    assert [c["params"]["kind"] for c in kinds(events, "card")] == ["vocab_review", "placement"]
    rows = [a for a in await activity(client, conversation) if a["name"] == "load_skill"]
    assert [(r["kind"], r["status"], r["summary"]) for r in rows] == [
        ("tool", "ok", {"skill": SKILL, "part": None})
    ]
    assert rows[0]["call_id"] == call["id"]


async def test_each_part_is_read_once_a_turn(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = [[load(), load()], [load("cloze"), load()], "Here is one."]

    await send(client, conversation, "Quiz me in the chat")

    first, second = results(script.calls[1][1])
    assert first.text.startswith(f'<skill name="{SKILL}">')
    assert second.status == "success" and "already read" in second.text
    part, again = results(script.calls[2][1])[2:]
    assert part.text.startswith(f'<skill name="{SKILL}" part="cloze">')
    assert get_skills()[SKILL].references["cloze"] in part.text
    assert "already read" in again.text
    rows = [a for a in await activity(client, conversation) if a["name"] == "load_skill"]
    assert [r["summary"] for r in rows] == [
        {"skill": SKILL, "part": None},
        {"skill": SKILL, "part": "cloze"},
    ]


async def test_skill_rounds_have_their_own_limit(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    parts = sorted(get_skills()[SKILL].references)
    script.replies = [[load(p)] for p in parts]

    await send(client, conversation, "Make up a question")

    # Free skill rounds, then they count as ordinary ones, then no tools.
    assert len(script.calls) == MAX_SKILL_ROUNDS + MAX_TOOL_ROUNDS + 1
    assert script.calls[-1][0] is None


async def test_skill_calls_dont_count_against_calls_per_round(
    client: AsyncClient, script: Script
) -> None:
    conversation = await ready(client)
    links = [tool_call("suggest_link", kind=k) for k in ("vocab_review", "placement", "learner")]
    script.replies = [[load(), *links], "Done."]

    await send(client, conversation, "What now?")

    assert [r.status for r in results(script.calls[1][1])] == ["success"] * 4
    assert len(await cards(client, conversation)) == 3


async def test_an_unknown_skill_is_an_error_result(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = [[load(name="../prompts/tutor_system"), load("nope")], "Sorry."]

    await send(client, conversation, "Question please")

    unknown, no_part = results(script.calls[1][1])
    assert unknown.status == "error" and f"skills: {SKILL}" in unknown.text
    assert no_part.status == "error" and "cloze" in no_part.text
    rows = [a for a in await activity(client, conversation) if a["name"] == "load_skill"]
    assert [(r["status"], r["summary"]) for r in rows] == [("failed", {}), ("failed", {})]


async def test_a_skill_read_earlier_is_left_out_of_later_turns(
    client: AsyncClient, script: Script
) -> None:
    conversation = await ready(client)
    script.replies = [[load()], "Which is right: ...?", "Correct!"]
    await send(client, conversation, "Ask me something")
    await send(client, conversation, "The first one")

    (kept,) = results(script.calls[-1][1])
    assert kept.text == (
        f"Read {SKILL} in an earlier turn; not kept here. Read it again if you need it."
    )
    # Listed in the system prompt, so the tutor knows it can read it again.
    assert f"- {SKILL}: " in system_text(script.calls[-1][1])
