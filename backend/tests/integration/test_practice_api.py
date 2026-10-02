"""Practice API (task 35): a whole set, coming back to it, one KC, errors.

No model is configured, so sets come from the placement bank (all choice4, graded by
code); open items are seeded directly to check what happens without a grading model.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import BaseMessage
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise.formats import parse_body
from app.adaptive.exercise.grader import Graded
from app.adaptive.exercise.worker import PracticeWorker
from app.adaptive.rules import get_rules
from app.agents.exercise_graph import ModelReply, StructuredCall
from app.api import practice as practice_api
from app.db.models import Attempt, Exercise, ExerciseSet, User
from tests.integration.test_chat_send import login
from tests.integration.test_exercise_answer import ITEMS, KC
from tests.integration.test_learner_api import switch_to

RULES = get_rules()


async def post(client: AsyncClient, url: str, body: dict[str, Any], expect: int = 200) -> Any:
    response = await client.post(url, json=body)
    assert response.status_code == expect, response.text
    return response.json()


async def get(client: AsyncClient, url: str, expect: int = 200) -> Any:
    response = await client.get(url)
    assert response.status_code == expect, response.text
    return response.json()


async def ready_set(client: AsyncClient, app: FastAPI, body: dict[str, Any]) -> dict[str, Any]:
    started = await post(client, "/practice/sets", body)
    worker: PracticeWorker = app.state.practice_worker
    await worker.wait_idle()
    state: dict[str, Any] = await get(client, f"/practice/sets/{started['id']}")
    assert state["status"] == "ready", state
    return state


def right(item: dict[str, Any], bank_key: dict[str, str]) -> dict[str, Any]:
    return {"choice": bank_key[item["content"]["stem"]]}


async def bank_keys(db: AsyncSession, set_id: str) -> dict[str, str]:
    rows = await db.scalars(select(Exercise).where(Exercise.set_id == uuid.UUID(set_id)))
    return {r.content["stem"]: r.answer["correct"] for r in rows}


async def test_a_whole_set(client: AsyncClient, app: FastAPI, db_session: AsyncSession) -> None:
    await login(client)
    assert await get(client, "/practice/sets") == []

    started = await post(client, "/practice/sets", {"origin": "learner"})
    assert started["status"] == "generating" and started["stage"]
    state = await ready_set(client, app, {"origin": "learner"})
    assert state["id"] == started["id"]  # the same set, now generated
    items = state["items"]
    assert len(items) == RULES.practice.set_size
    assert all(i["format"] == "choice4" and i["from_bank"] for i in items)
    assert all(i["answer"] is None and i["result"] is None for i in items)
    assert state["how_made"]["from_bank"] == len(items)
    assert state["summary"] is None
    keys = await bank_keys(db_session, state["id"])

    first, *rest = items
    wrong = next(o for o in first["content"]["options"] if o != keys[first["content"]["stem"]])
    answered = await post(
        client, f"/practice/exercises/{first['id']}/answer", {"choice": wrong, "latency_ms": 900}
    )
    assert not answered["set_done"]
    result = answered["item"]["result"]
    assert result["correct"] is False and result["response"] == {"choice": wrong}
    assert answered["item"]["answer"]["correct"] == keys[first["content"]["stem"]]
    # Only the first answer counts.
    again = await post(client, f"/practice/exercises/{first['id']}/answer", right(first, keys))
    assert again["item"]["result"]["correct"] is False

    # Leaving and starting again comes back to this set.
    assert (await post(client, "/practice/sets", {}))["id"] == state["id"]

    for item in rest:
        answered = await post(client, f"/practice/exercises/{item['id']}/answer", right(item, keys))
    assert answered["set_done"]

    done = await get(client, f"/practice/sets/{state['id']}")
    assert done["status"] == "done" and done["finished_at"]
    summary = done["summary"]
    assert (summary["total"], summary["correct"]) == (len(items), len(items) - 1)
    assert sum(k["items"] for k in summary["kcs"]) == len(items)
    for change in summary["kcs"]:
        assert change["before"] == {"p_mastery": None, "state": None, "learned": False}
        assert change["after"]["p_mastery"] is not None
        assert change["progress"]["formats_passed"] in ([], ["choice4"])

    [brief] = await get(client, "/practice/sets")
    assert (brief["id"], brief["status"], brief["origin"]) == (state["id"], "done", "learner")
    assert (brief["total"], brief["answered"], brief["correct"]) == (10, 10, 9)


async def test_a_set_for_one_kc(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    state = await ready_set(client, app, {"origin": "learner", "kc_id": KC})
    assert state["focus_kc"]["id"] == KC and state["focus_kc"]["name_zh"]
    body = await post(client, "/practice/sets", {"kc_id": "g.no_such_kc"}, expect=422)
    assert body["detail"]["code"] == "unknown_kc"


async def test_finishing_a_set_prepares_the_next(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    app.state.practice_worker.prefetch_enabled = True
    await login(client)
    state = await ready_set(client, app, {})
    keys = await bank_keys(db_session, state["id"])
    *answered, last = state["items"]
    for item in answered:
        await post(client, f"/practice/exercises/{item['id']}/answer", right(item, keys))

    # Reporting the last open item finishes the set too.
    reported = await post(client, f"/practice/exercises/{last['id']}/report", {})
    assert reported["set_done"]
    assert reported["item"]["status"] == "reported" and reported["item"]["answer"]
    await app.state.practice_worker.wait_idle()
    ahead = await db_session.scalar(
        select(ExerciseSet).where(ExerciseSet.origin == "prefetch", ExerciseSet.status == "ready")
    )
    assert ahead is not None
    summary = (await get(client, f"/practice/sets/{state['id']}"))["summary"]
    assert summary["total"] == len(answered)  # the reported item counts for nothing


async def test_other_learners_sets_are_not_found(client: AsyncClient, app: FastAPI) -> None:
    await login(client, "a@example.com")
    state = await ready_set(client, app, {})
    item = state["items"][0]
    await login(client, "b@example.com")
    body = await get(client, f"/practice/sets/{state['id']}", expect=404)
    assert body["detail"]["code"] == "practice_set_not_found"
    body = await post(client, f"/practice/exercises/{item['id']}/answer", {"choice": "x"}, 404)
    assert body["detail"]["code"] == "exercise_not_found"
    await post(client, f"/practice/exercises/{item['id']}/report", {}, 404)
    await switch_to(client, "a@example.com")
    await get(client, f"/practice/sets/{state['id']}")


async def test_answers_that_do_not_fit_are_refused(client: AsyncClient, app: FastAPI) -> None:
    await login(client)
    state = await ready_set(client, app, {})
    item = state["items"][0]
    url = f"/practice/exercises/{item['id']}/answer"
    for body in ({"text": "lives"}, {"choice": "not an option"}, {}):
        reply = await post(client, url, body, expect=422)
        assert reply["detail"]["code"] in ("invalid_response", "validation_error"), reply


async def open_item(db: AsyncSession, email: str) -> int:
    user_id = await db.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    exercise_set = ExerciseSet(user_id=user_id, origin="dashboard", status="ready", kc_plan=[])
    db.add(exercise_set)
    await db.flush()
    content, key = ITEMS["translate"]
    body = parse_body("translate", content, key)
    item = Exercise(
        user_id=user_id,
        set_id=exercise_set.id,
        position=0,
        kc_id=KC,
        format="translate",
        content=body.content.model_dump(mode="json"),
        answer=body.answer.model_dump(mode="json"),
        difficulty=0.0,
        status="ok",
    )
    db.add(item)
    await db.commit()
    return item.id


async def test_without_a_grading_model_nothing_is_saved(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    item = await open_item(db_session, "learner@example.com")
    url = f"/practice/exercises/{item}/answer"
    body = await post(client, url, {"text": "She walk to work every day."}, expect=503)
    assert body["detail"]["code"] == "no_llm_configured"
    assert await db_session.scalar(select(func.count()).select_from(Attempt)) == 0
    # The reference answer itself needs no model (Q34a).
    answered = await post(client, url, {"text": "She walks to work."})
    assert answered["item"]["result"]["correct"] is True and answered["set_done"]


async def test_the_page_never_sees_where_an_own_sentence_came_from(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    user_id = await db_session.scalar(select(User.id).where(User.email == "learner@example.com"))
    assert user_id is not None
    exercise_set = ExerciseSet(user_id=user_id, origin="dashboard", status="ready", kc_plan=[])
    db_session.add(exercise_set)
    await db_session.flush()
    body = parse_body(
        "rewrite_own",
        {"instruction": "Fix it.", "original": "He go to work.", "evidence_id": 7},
        {"accepted": ["He goes to work."], "explanation": "Third person takes -s."},
    )
    db_session.add(
        Exercise(
            user_id=user_id,
            set_id=exercise_set.id,
            position=0,
            kc_id=KC,
            format="rewrite_own",
            content=body.content.model_dump(mode="json"),
            answer=body.answer.model_dump(mode="json"),
            difficulty=0.0,
            status="ok",
        )
    )
    await db_session.commit()
    [item] = (await get(client, f"/practice/sets/{exercise_set.id}"))["items"]
    assert item["content"] == {"instruction": "Fix it.", "original": "He go to work."}


async def test_an_open_answer_graded_by_the_model(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    graded = Graded(
        correct=False,
        explanation="The verb needs -s.",
        corrected="She walks to work.",
        other_mistakes=[],
    )

    def fake_call(ctx: object, config: dict[str, Any], task: str) -> StructuredCall:
        assert task == "exercise_grade" and config["metadata"]["user_id"]

        async def call(messages: Sequence[BaseMessage], schema: type[BaseModel]) -> ModelReply:
            return ModelReply(graded, "fake:grader")

        return call

    monkeypatch.setattr(practice_api, "structured_call", fake_call)
    await login(client)
    item = await open_item(db_session, "learner@example.com")
    answered = await post(
        client, f"/practice/exercises/{item}/answer", {"text": "She walk to work."}
    )
    result = answered["item"]["result"]
    assert result["correct"] is False
    assert result["feedback"]["corrected"] == "She walks to work."
    assert result["feedback"]["model"] == "fake:grader"
