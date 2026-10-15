"""give_quiz in the chat (ADR 0044 §4): the call starts a quiz set and shows its card;
the set's results reach the tutor's context on later turns."""

import uuid
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise.formats import parse_body
from app.adaptive.rules import get_rules
from app.agents.chat_graph import quiz_rule
from app.db.models import Attempt, Exercise, ExerciseSet, TutorCard
from app.prompts import load_prompt
from app.providers.config import TutorPick
from tests.integration.test_chat_tools import (
    Script,
    _clear_caches,  # noqa: F401
    activity,
    kinds,
    ready,
    send,
    system_text,
    tool_call,
)
from tests.integration.test_quiz_answer import CHECKS
from tests.integration.test_workspace_tools import results
from tests.integration.test_workspace_tools import script as tool_script

KC = "g.present_simple_third_person"
script = tool_script


@pytest.fixture(autouse=True)
def no_generation(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sets stay generating: the fake chat model cannot write exercises, and these
    tests fill the sets themselves."""
    monkeypatch.setattr(app.state.practice_worker, "_spawn", lambda *a, **k: None)


async def quiz_sets(db: AsyncSession) -> list[ExerciseSet]:
    return list(await db.scalars(select(ExerciseSet).where(ExerciseSet.origin == "quiz")))


async def test_give_quiz_starts_a_set_and_shows_its_card(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    script.replies = [
        [tool_call("give_quiz", kc_id=KC, purpose="quiz", asked=True)],
        "Try the card.",
    ]

    status, events, _ = await send(client, conversation, "Test me on -s, please.")

    assert status == 200
    (card,) = kinds(events, "card")
    (row,) = await quiz_sets(db_session)
    assert (row.status, row.quiz_purpose, row.focus_kc_id) == ("generating", "quiz", KC)
    assert card["kind"] == "quiz" and card["status"] == "info"
    assert card["params"] == {
        "set_id": str(row.id),
        "kc_id": KC,
        "purpose": "quiz",
        "proactive": False,
    }
    assert card["display"]["kc"]["id"] == KC
    assert card["display"]["pass_score"] == get_rules().course.pass_score
    (result,) = results(script)
    assert "Quiz card shown: the pass quiz" in result.text
    assert "Do not ask the questions" in result.text
    steps = [a["name"] for a in await activity(client, conversation)]
    assert "give_quiz" in steps


async def test_refused_calls_show_no_card(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    for _ in range(get_rules().course.generated_quizzes_per_day):
        script.replies = [[tool_call("give_quiz", kc_id=KC, purpose="quiz", asked=True)], "Try it."]
        await send(client, conversation, "Quiz me.")
    script.replies = [
        [
            tool_call("give_quiz", kc_id=KC, purpose="quiz", asked=True),
            tool_call("give_quiz", kc_id="g.no_such_kc", purpose="check", asked=True),
        ],
        "Let's practise here instead.",
    ]

    _, events, _ = await send(client, conversation, "Again!")

    assert kinds(events, "card") == []
    limit, unknown = (m.text for m in results(script, call=-1)[-2:])
    assert "already taken today's pass quizzes" in limit
    assert unknown.startswith("Error: unknown kc_id"), unknown
    assert len(await quiz_sets(db_session)) == get_rules().course.generated_quizzes_per_day


async def answer(db: AsyncSession, set_id: uuid.UUID, rights: list[bool]) -> None:
    """Fill the set with checks answered right or wrong, and finish it."""
    row = await db.get(ExerciseSet, set_id)
    assert row is not None
    user_id = row.user_id
    for position, right in enumerate(rights):
        body = parse_body("concept_choice", *CHECKS["concept_choice"])
        item = Exercise(
            user_id=user_id,
            set_id=set_id,
            position=position,
            kc_id=KC,
            format="concept_choice",
            content=body.content.model_dump(mode="json"),
            answer=body.answer.model_dump(mode="json"),
            difficulty=0.0,
            status="ok",
        )
        db.add(item)
        await db.flush()
        choice = body.answer.correct if right else "past"
        db.add(
            Attempt(
                user_id=user_id,
                exercise_id=item.id,
                response={"choice": choice},
                correct=right,
                latency_ms=1000,
            )
        )
    row.status = "done"
    await db.commit()


async def test_the_next_turn_sees_the_results(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    script.replies = [
        [tool_call("give_quiz", kc_id=KC, purpose="check", asked=True)],
        "Try the card.",
    ]
    await send(client, conversation, "Check I understand.")
    (row,) = await quiz_sets(db_session)
    script.calls.clear()

    script.replies = ["Still writing."]
    await send(client, conversation, "Is it ready?")
    assert "understanding check on" in system_text(script.calls[0][1])
    assert "questions still being written" in system_text(script.calls[0][1])

    await answer(db_session, row.id, [True, False])
    script.calls.clear()
    script.replies = ["Let's look at the one you missed."]
    await send(client, conversation, "Done!")
    prompt = system_text(script.calls[0][1])
    assert "all answered, 1 of 2 right" in prompt
    assert "answered 'past', expected 'he is one person'" in prompt


async def test_a_topic_finds_the_grammar_point(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    """Free chat gives no id for most points; the tutor names one (ADR 0046 §1)."""
    conversation = await ready(client)
    script.replies = [
        [tool_call("give_quiz", topic="subject + verb word order", purpose="quiz", asked=True)],
        "Try the card.",
    ]

    _, events, _ = await send(client, conversation, "出点题给我测试吧")

    (card,) = kinds(events, "card")
    assert card["params"]["kc_id"] == "g.word_order_svo"
    (row,) = await quiz_sets(db_session)
    assert row.focus_kc_id == "g.word_order_svo"


async def test_an_unclear_topic_lists_candidates(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    script.replies = [
        [
            tool_call("give_quiz", topic="present perfect", purpose="quiz", asked=True),
            tool_call("give_quiz", topic="photosynthesis", purpose="quiz", asked=True),
            tool_call("give_quiz", purpose="quiz", asked=True),
        ],
        "Which part of the present perfect?",
    ]

    _, events, _ = await send(client, conversation, "Test me on the present perfect.")

    assert kinds(events, "card") == []
    assert await quiz_sets(db_session) == []
    several, none, neither = (m.text for m in results(script, call=-1)[-3:])
    assert "matches several grammar points" in several
    assert "g.present_perfect_for_since" in several
    assert "no grammar point matches" in none
    assert "give kc_id or topic" in neither


def unasked(kc_id: str = KC, purpose: str = "check") -> dict[str, object]:
    return tool_call("give_quiz", kc_id=kc_id, purpose=purpose, asked=False)


async def refusal(script: Script) -> str:
    return results(script, call=-1)[-1].text


async def test_an_unasked_quiz_is_only_a_check(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    """ADR 0046 §3: a pass quiz changes mastery, so the learner has to ask for it."""
    conversation = await ready(client)
    script.replies = [[unasked(purpose="quiz")], "Shall we test it?"]
    _, events, _ = await send(client, conversation, "I see, -s after he.")
    assert kinds(events, "card") == []
    assert "use purpose check, or ask first" in await refusal(script)

    script.replies = [[unasked()], "Try the card."]
    _, events, _ = await send(client, conversation, "Got it.")
    (card,) = kinds(events, "card")
    assert card["params"]["proactive"] is True and card["params"]["purpose"] == "check"


async def test_unasked_quizzes_are_spaced_and_once_per_point(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    other = "g.be_present"
    script.replies = [[unasked()], "Try the card."]
    await send(client, conversation, "Got it.")

    script.replies = [[unasked(other)], "Any questions?"]
    _, events, _ = await send(client, conversation, "And am / is / are?")
    assert kinds(events, "card") == []
    assert "only a few minutes ago" in await refusal(script)

    # Past the gap: another point is fine, the same one is not.
    await db_session.execute(
        update(TutorCard)
        .where(TutorCard.kind == "quiz")
        .values(created_at=func.now() - timedelta(minutes=11))
    )
    await db_session.commit()
    script.replies = [[unasked()], "Let's talk it through."]
    _, events, _ = await send(client, conversation, "Still a bit unsure about -s.")
    assert kinds(events, "card") == []
    assert "already gave an unasked check" in await refusal(script)
    script.replies = [[unasked(other)], "Try the card."]
    _, events, _ = await send(client, conversation, "And am / is / are?")
    assert len(kinds(events, "card")) == 1

    # Asked for: no limits.
    script.replies = [
        [tool_call("give_quiz", kc_id=KC, purpose="check", asked=True)],
        "Here it is.",
    ]
    _, events, _ = await send(client, conversation, "Test me on -s again.")
    assert len(kinds(events, "card")) == 1


async def test_the_learner_can_turn_unasked_quizzes_off(
    client: AsyncClient, db_session: AsyncSession, script: Script
) -> None:
    conversation = await ready(client)
    assert (await client.put("/tutor", json={"quiz_proactive": False})).status_code == 200
    script.replies = [[unasked()], "Want a quick check?"]
    _, events, _ = await send(client, conversation, "Got it.")
    assert kinds(events, "card") == []
    assert "turned off quizzes they did not ask for" in await refusal(script)

    script.replies = [
        [tool_call("give_quiz", kc_id=KC, purpose="check", asked=True)],
        "Here it is.",
    ]
    _, events, _ = await send(client, conversation, "Yes, check me.")
    assert len(kinds(events, "card")) == 1


async def test_the_prompt_follows_the_setting(client: AsyncClient, script: Script) -> None:
    conversation = await ready(client)
    script.replies = ["Hi!"]
    await send(client, conversation, "Hello")
    first = system_text(script.calls[0][1])
    assert "### Quizzes" in first
    assert load_prompt("tutor_quiz_proactive") in first

    assert (await client.put("/tutor", json={"quiz_proactive": False})).status_code == 200
    script.replies = ["Hi again!"]
    await send(client, conversation, "Hello again")
    second = system_text(script.calls[1][1])
    assert load_prompt("tutor_quiz_on_request") in second
    assert load_prompt("tutor_quiz_proactive") not in second


def test_a_lesson_tests_whatever_the_setting() -> None:
    off = TutorPick(quiz_proactive=False)
    assert quiz_rule(off, lesson=True) == load_prompt("tutor_quiz_proactive")
    assert quiz_rule(off, lesson=False) == load_prompt("tutor_quiz_on_request")
