"""suggest_lesson (ADR 0054 §1): a card that opens the course's lesson on a grammar
point; a locked lesson gives way to the earliest open one it waits for."""

import pytest
from httpx import AsyncClient

from app.cards.tools import ToolCallError, parse_args
from tests.integration.test_chat_send import send
from tests.integration.test_chat_tools import (  # noqa: F401 (fixtures)
    Script,
    _clear_caches,
    kinds,
    script,
    system_text,
    tool_call,
)
from tests.integration.test_lesson import LOCKED, OPEN, no_generation, ready, start  # noqa: F401
from tests.integration.test_workspace_tools import results

# For a new learner, lesson 2 is open and the present perfect is far down a locked chain
# that starts at lesson 1 (word order).
SECOND = "g.be_present"
FAR = "g.present_perfect_for_since"


async def test_a_lesson_conversation_points_off_topic_questions_to_their_lesson(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await ready(client)
    conversation = (await start(client, OPEN))["conversation"]["id"]
    script.replies = [
        [tool_call("suggest_lesson", kc_id=SECOND)],
        "That is lesson 2; back to word order.",
    ]

    status, events, _ = await send(client, conversation, "How do I use am / is / are?")

    assert status == 200
    (card,) = kinds(events, "card")
    assert (card["kind"], card["status"]) == ("lesson", "info")
    assert card["params"] == {"kc_id": SECOND, "number": 2}
    assert card["display"]["kc"]["id"] == SECOND
    (result,) = results(script)
    assert result.text.startswith("(card ")
    assert "lesson 2" in result.text and "(not started)" in result.text
    prompt = system_text(script.calls[0][1])
    assert "answer it in one sentence" in prompt and "`suggest_lesson`" in prompt
    # The card opens the lesson like the course page does.
    opened = await start(client, card["params"]["kc_id"])
    assert opened["conversation"]["focus_kc"]["id"] == SECOND


async def test_a_locked_lesson_opens_the_earliest_lesson_it_waits_for(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await ready(client)
    conversation = (await start(client, SECOND))["conversation"]["id"]
    script.replies = [[tool_call("suggest_lesson", topic="present perfect for since")], "Later."]

    _, events, _ = await send(client, conversation, "What about for and since?")

    (card,) = kinds(events, "card")
    params = card["params"]
    assert (params["kc_id"], params["number"]) == (OPEN, 1)
    assert params["asked_kc_id"] == FAR and params["asked_number"] > 1
    assert card["display"]["asked_kc"]["id"] == FAR
    (result,) = results(script)
    assert "is locked until the lessons it builds on are passed" in result.text
    assert "opens lesson 1 first, with 5 more lessons after it" in result.text


async def test_refused_lesson_cards(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await ready(client)
    conversation = (await start(client, OPEN))["conversation"]["id"]
    script.replies = [
        [
            tool_call("suggest_lesson", kc_id=OPEN),
            tool_call("suggest_lesson", kc_id=LOCKED),
            tool_call("suggest_lesson", topic="zzz qqq"),
        ],
        "Let's stay here.",
    ]

    _, events, _ = await send(client, conversation, "What next?")

    assert kinds(events, "card") == []
    same, waits, unknown = (m.text for m in results(script))
    assert "is the lesson of this conversation" in same
    # The third person -s waits for this very lesson.
    assert "locked until this conversation's lesson is passed" in waits
    assert "no grammar point matches" in unknown


def test_a_lesson_card_needs_a_grammar_point() -> None:
    with pytest.raises(ToolCallError, match="give kc_id or topic"):
        parse_args("suggest_lesson", {"topic": "  "})
