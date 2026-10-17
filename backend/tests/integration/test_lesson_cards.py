"""suggest_lesson (ADR 0054 §1): a card that opens the course's lesson on a grammar
point; a locked lesson gives way to the earliest open one it waits for."""

from httpx import AsyncClient

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


async def test_naming_no_lesson_shows_the_next_one(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    """qwen-plus calls suggest_lesson without arguments (task 98.5)."""
    await ready(client)
    lesson = (await start(client, OPEN))["conversation"]["id"]
    script.replies = [
        [tool_call("suggest_lesson")],
        "Lesson 2 is next.",
        [tool_call("suggest_lesson")],
        "Start here.",
    ]

    _, events, _ = await send(client, lesson, "What comes after this?")
    (card,) = kinds(events, "card")
    assert card["params"] == {"kc_id": SECOND, "number": 2}

    free = (await client.post("/conversations")).json()["id"]
    _, events, _ = await send(client, free, "你决定吧")
    (card,) = kinds(events, "card")
    assert card["params"] == {"kc_id": OPEN, "number": 1}
    for result in results(script):
        assert "No grammar point was named" in result.text
        # The card only shows the way (task 98.5: the tutor said they were in the lesson).
        assert "when they choose" in result.text and "don't start teaching it here" in result.text


async def test_a_name_taught_over_several_lessons_opens_the_first(
    client: AsyncClient,
    script: Script,  # noqa: F811
) -> None:
    await ready(client)
    course = (await client.get("/course")).json()["lessons"]
    first = min(
        (lesson for lesson in course if lesson["kc_id"].startswith("g.present_perfect")),
        key=lambda lesson: lesson["number"],
    )
    conversation = (await start(client, SECOND))["conversation"]["id"]
    script.replies = [[tool_call("suggest_lesson", topic="present perfect")], "Later."]

    _, events, _ = await send(client, conversation, "我想学现在完成时")

    (card,) = kinds(events, "card")
    assert card["params"]["asked_kc_id"] == first["kc_id"]
    (result,) = results(script)
    assert "is taught over several lessons; this is the first of them" in result.text
