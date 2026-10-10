"""Speaking sessions through the API (task 58.5, ADR 0029 §5-6, Q58b-e, Q58g)."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.exercise import worker as exercise_worker
from app.adaptive.rules import get_rules
from app.db.models import Conversation, SkillEstimate, SpeakingSession, User
from app.speaking import sessions
from app.speaking.summary import Expression, Mistake, Natural, SpeakingSummary
from tests.integration.test_chat_send import (
    _clear_caches,  # noqa: F401
    connect,
    fake_models,
    history,
    login,
    parse_sse,
    send,
)

RULES = get_rules()


class FakeSummarizer:
    """Stands in for the `speaking_summary` route."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.fail = False

    def get_structured_llm(
        self, ctx: Any, task: str, schema: type[BaseModel]
    ) -> Runnable[Any, Any]:
        assert task == "speaking_summary" and schema is SpeakingSummary

        async def run(messages: list[BaseMessage], config: RunnableConfig | None = None) -> Any:
            if self.fail:
                raise RuntimeError("model glitch")
            self.prompts.append("\n".join(str(m.content) for m in messages))
            return SpeakingSummary(
                went_well=["Kept the conversation going.", " "],
                mistakes=[
                    Mistake(quote="I wants", correction="I want", explanation="主语是 I。"),
                    Mistake(quote="never said", correction="x", explanation="made up"),
                ],
                more_natural=[Natural(quote="give me", natural="could I have", note="更礼貌")],
                next_expressions=[
                    Expression(expression="for here or to go", meaning="堂食还是外带")
                ],
                intelligibility="mostly",
            )

        return RunnableLambda(run)


@pytest.fixture
def summarizer(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSummarizer]:
    fake = FakeSummarizer()
    monkeypatch.setattr(exercise_worker, "get_structured_llm", fake.get_structured_llm)
    fake_models(monkeypatch)  # speaking_coach's streamed replies
    yield fake


async def ready(client: AsyncClient) -> None:
    await login(client)
    await connect(client, "deepseek")


async def start(client: AsyncClient, scenario_id: str | None = "ordering_food") -> dict[str, Any]:
    response = await client.post(
        "/speaking/sessions", json={"scenario_id": scenario_id, "locale": "zh-CN"}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def row(session: AsyncSession, session_id: str) -> SpeakingSession:
    session.expire_all()
    found = await session.get(SpeakingSession, uuid.UUID(session_id))
    assert found is not None
    return found


async def test_scenarios_are_listed_for_the_learners_level(client: AsyncClient) -> None:
    await login(client)
    body = (await client.get("/speaking/scenarios")).json()
    assert body["level"] == RULES.practice.default_level
    suits = [s["suits"] for s in body["scenarios"]]
    assert len(suits) == 10 and suits == sorted(suits, reverse=True)
    first = body["scenarios"][0]
    assert first["title_zh"] and first["learner_goal_zh"] and first["target_expressions"]
    assert "role" not in first and "opening" not in first  # the coach's, not the page's


async def test_a_session_opens_talks_and_stays_off_the_chat_list(
    client: AsyncClient, db_session: AsyncSession, summarizer: FakeSummarizer
) -> None:
    await ready(client)
    body = await start(client)
    assert (body["status"], body["scenario_id"], body["turns"]) == (
        "active",
        "ordering_food",
        0,
    )
    conversation_id = body["conversation_id"]
    conversation = await db_session.get(Conversation, uuid.UUID(conversation_id))
    assert conversation is not None
    assert (conversation.purpose, conversation.title) == ("speaking", "口语：餐厅点餐")  # noqa: RUF001
    assert (await client.get("/conversations")).json() == []  # Q58g

    opening = await client.post(f"/conversations/{conversation_id}/opening")  # Q58e
    assert opening.status_code == 200 and parse_sse(opening.text)[-1][0] == "done"
    status, events, _ = await send(client, conversation_id, "I wants a burger, give me one.")
    assert status == 200 and events[-1][0] == "done"

    detail = (await client.get(f"/speaking/sessions/{body['id']}")).json()
    assert (detail["turns"], detail["spoken_turns"], detail["spoken_seconds"]) == (1, 0, 0)

    for payload in ({"scenario_id": "nope"},):
        response = await client.post("/speaking/sessions", json=payload)
        assert (response.status_code, response.json()["detail"]["code"]) == (
            404,
            "scenario_not_found",
        )
    free = await start(client, None)
    conversation = await db_session.get(Conversation, uuid.UUID(free["conversation_id"]))
    assert conversation is not None and conversation.title == "口语：自由聊"  # noqa: RUF001


async def test_ending_sums_up_with_checked_quotes_and_closes_the_session(
    client: AsyncClient, db_session: AsyncSession, summarizer: FakeSummarizer
) -> None:
    await ready(client)
    body = await start(client)
    conversation_id = body["conversation_id"]
    await send(client, conversation_id, "I wants a burger, give me one.")

    ended = await client.post(f"/speaking/sessions/{body['id']}/end")

    assert ended.status_code == 200
    detail = ended.json()
    assert detail["status"] == "done" and detail["ended_at"] is not None
    summary = detail["summary"]
    assert summary["went_well"] == ["Kept the conversation going."]
    assert [m["quote"] for m in summary["mistakes"]] == ["I wants"]  # made-up quote dropped
    assert [n["natural"] for n in summary["more_natural"]] == ["could I have"]
    assert (summary["intelligibility"], detail["intelligibility"]) == ("mostly", "mostly")
    [prompt] = summarizer.prompts
    assert "Ordering at a restaurant" in prompt and "Learner: I wants a burger" in prompt
    assert "Simplified Chinese" in prompt
    # Typed turns only: speaking ability does not move (Q58d).
    assert not (await row(db_session, body["id"])).counted

    # Ended: no more turns; ending again changes nothing and calls no model.
    status, _, error = await send(client, conversation_id, "One more thing.")
    assert (status, error["detail"]["code"]) == (409, "speaking_ended")
    again = await client.post(f"/speaking/sessions/{body['id']}/end")
    assert again.json()["summary"] == summary and len(summarizer.prompts) == 1


async def test_enough_spoken_turns_move_speaking_ability_once(
    client: AsyncClient, db_session: AsyncSession, summarizer: FakeSummarizer
) -> None:
    await ready(client)
    body = await start(client)
    await send(client, body["conversation_id"], "I wants a burger, give me one.")
    await db_session.execute(
        update(SpeakingSession)
        .where(SpeakingSession.id == uuid.UUID(body["id"]))
        .values(spoken_turns=RULES.speaking.min_spoken_turns)
    )
    await db_session.commit()

    await client.post(f"/speaking/sessions/{body['id']}/end")

    assert (await row(db_session, body["id"])).counted
    user = await db_session.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    ability = await db_session.get(SkillEstimate, (user.id, "speaking"))
    assert ability is not None and ability.attempts == 1
    # "mostly" (0.75) at the learner's own level beats the 0.5 expected there.
    assert ability.rating > RULES.difficulty.cefr_anchor[RULES.practice.default_level]


async def test_a_failed_summary_can_be_tried_again(
    client: AsyncClient, db_session: AsyncSession, summarizer: FakeSummarizer
) -> None:
    await ready(client)
    body = await start(client)
    await send(client, body["conversation_id"], "I wants a burger, give me one.")
    summarizer.fail = True

    failed = (await client.post(f"/speaking/sessions/{body['id']}/end")).json()
    assert (failed["status"], failed["summary"]) == ("failed", None)

    summarizer.fail = False
    done = (await client.post(f"/speaking/sessions/{body['id']}/end")).json()
    assert done["status"] == "done" and done["summary"] is not None


async def test_nothing_said_ends_without_a_call(
    client: AsyncClient, summarizer: FakeSummarizer
) -> None:
    await ready(client)
    body = await start(client)
    detail = (await client.post(f"/speaking/sessions/{body['id']}/end")).json()
    assert (detail["status"], detail["summary"]) == ("done", None)
    assert summarizer.prompts == []


async def test_idle_sessions_are_summed_up_when_the_page_opens(
    client: AsyncClient, db_session: AsyncSession, summarizer: FakeSummarizer
) -> None:
    await ready(client)
    idle, fresh = await start(client), await start(client, "self_intro")
    for body in (idle, fresh):
        await send(client, body["conversation_id"], "I wants a burger, give me one.")
    await db_session.execute(
        update(Conversation)
        .where(Conversation.id == uuid.UUID(idle["conversation_id"]))
        .values(updated_at=datetime.now(UTC) - timedelta(minutes=RULES.speaking.idle_minutes + 1))
    )
    await db_session.commit()

    page = (await client.get("/speaking/sessions")).json()

    assert [i["id"] for i in page["items"]] == [fresh["id"], idle["id"]]
    assert page["next_before"] is None
    # Summed up after the response (Q58c).
    assert (await row(db_session, idle["id"])).status == "done"
    assert (await row(db_session, fresh["id"])).status == "active"


async def test_paging(client: AsyncClient, summarizer: FakeSummarizer) -> None:
    await ready(client)
    ids = [(await start(client))["id"] for _ in range(3)]
    first = (await client.get("/speaking/sessions", params={"limit": 2})).json()
    assert [i["id"] for i in first["items"]] == ids[::-1][:2]
    rest = (
        await client.get("/speaking/sessions", params={"limit": 2, "before": first["next_before"]})
    ).json()
    assert [i["id"] for i in rest["items"]] == [ids[0]] and rest["next_before"] is None


async def test_a_fixed_transcript_marks_its_turn(
    client: AsyncClient, db_session: AsyncSession, summarizer: FakeSummarizer
) -> None:
    await ready(client)
    body = await start(client)
    await send(client, body["conversation_id"], "I wants a burger.")
    [turn] = [m for m in await history(client, body["conversation_id"]) if m["role"] == "user"]
    url = f"/speaking/sessions/{body['id']}/corrections"

    missing = await client.post(url, json={"message_id": "not-a-turn"})
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "message_not_found")
    fixed = await client.post(url, json={"message_id": turn["id"]})
    assert fixed.status_code == 204
    assert (await row(db_session, body["id"])).corrected_message_ids == [turn["id"]]


async def test_sessions_are_private_and_deletable(
    client: AsyncClient, db_session: AsyncSession, summarizer: FakeSummarizer
) -> None:
    await ready(client)
    body = await start(client)

    await client.post("/auth/logout")
    await login(client, "other@example.com")
    for method, path in (
        ("GET", f"/speaking/sessions/{body['id']}"),
        ("POST", f"/speaking/sessions/{body['id']}/end"),
        ("DELETE", f"/speaking/sessions/{body['id']}"),
    ):
        response = await client.request(method, path)
        assert (response.status_code, response.json()["detail"]["code"]) == (
            404,
            "session_not_found",
        )
    assert (await client.get("/speaking/sessions")).json()["items"] == []

    await client.post("/auth/logout")
    await client.post(
        "/auth/login", json={"email": "learner@example.com", "password": "password123"}
    )
    assert (await client.delete(f"/speaking/sessions/{body['id']}")).status_code == 204
    db_session.expire_all()
    assert await db_session.get(Conversation, uuid.UUID(body["conversation_id"])) is None
    assert await db_session.get(SpeakingSession, uuid.UUID(body["id"])) is None


def test_scenario_level_keeps_the_learner_within_the_range() -> None:
    from app.speaking.scenarios import get_scenarios

    interview = get_scenarios().get("job_interview")  # B1-C1
    assert interview is not None
    assert sessions.scenario_level("A2", interview) == "B1"
    assert sessions.scenario_level("B2", interview) == "B2"
    assert sessions.scenario_level("C2", interview) == "C1"
    assert sessions.scenario_level("A1", None) == "A1"
