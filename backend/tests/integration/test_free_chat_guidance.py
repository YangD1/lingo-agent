"""Free chat tells a question from "you decide" (ADR 0054 §3); conversations with a
purpose of their own keep their own guidance instead."""

from httpx import AsyncClient

from app.prompts import load_prompt
from tests.integration.test_chat_send import send
from tests.integration.test_chat_tools import (  # noqa: F401 (fixtures)
    Script,
    _clear_caches,
    ready,
    script,
    system_text,
)
from tests.integration.test_lesson import OPEN, no_generation, start  # noqa: F401

SECTION = "## This conversation: free chat"

ID_RULE = "are for your tools only: in replies,\n  call a grammar point, lesson or card by its name"


async def test_free_chat_sorts_out_what_the_learner_wants(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    conversation = await ready(client)
    script.replies = ["Present perfect: have + past participle."]

    status, _, _ = await send(client, conversation, "How do I use the present perfect?")

    assert status == 200
    prompt = system_text(script.calls[0][1])
    assert SECTION in prompt
    assert "answer it fully and clearly, then stop" in prompt
    assert "don't ask them back what they want" in prompt
    assert "Say it once:\n  before the call or after the card appears, not both." in prompt
    # "You decide" has a next step to go by (ADR 0054 §4).
    assert "Suggested next by the learning engine" in prompt
    # The base rule no longer asks every reply to end with a question.
    assert "after answering a question, stop instead of adding one" in prompt
    # Its context lists grammar points by id, for the tools (task 99.2).
    assert ID_RULE in prompt
    # What was said before a tool call is not said again after it (task 99.3).
    assert (
        "what you wrote before\nthe call: don't say it again, neither the advice nor the reason"
        in prompt
    )


async def test_lessons_and_practice_keep_their_own_guidance(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await ready(client)
    lesson = (await start(client, OPEN))["conversation"]["id"]
    practice = (await client.post("/conversations", json={"focus_kc_id": OPEN})).json()["id"]
    script.replies = ["Back to word order.", "Let's practise."]

    await send(client, lesson, "What is the present perfect?")
    await send(client, practice, "Hi")

    lesson_prompt, practice_prompt = (system_text(messages) for _, messages in script.calls)
    assert "a lesson of the grammar course" in lesson_prompt
    assert ID_RULE in lesson_prompt
    assert "## This conversation: grammar practice" in practice_prompt
    assert SECTION not in lesson_prompt and SECTION not in practice_prompt
    assert "Suggested next by the learning engine" not in lesson_prompt
    assert load_prompt("free_chat").startswith(SECTION)
