"""After a realtime call hangs up (task 61.3, ADR 0030 §6, Q61g-i): reflection, the
summary and the speaking time, without the relay: the transcript is saved the way the
relay saves it."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.evidence import ChatEvidence
from app.adaptive.rules import get_rules
from app.db.models import SpeakingSession, Tenant, User
from app.memory.worker import ReflectionWorker
from app.providers.realtime_session import Subtitle
from app.realtime import calls
from app.realtime.transcript import Transcript
from app.speaking import sessions
from app.speaking.evidence import kept_evidence
from tests.integration.test_chat_send import (
    _clear_caches,  # noqa: F401
    connect,
    login,
)
from tests.integration.test_speaking_api import FakeSummarizer, summarizer  # noqa: F401


@dataclass(frozen=True)
class Call:
    id: uuid.UUID
    conversation_id: uuid.UUID


async def a_call(
    app: FastAPI, db_session: AsyncSession, *, seconds: float, said: list[str]
) -> Call:
    """A realtime call that lasted `seconds`, the learner saying `said`, hung up."""
    user = await db_session.scalar(select(User))
    tenant = await db_session.scalar(select(Tenant))
    assert user is not None and tenant is not None
    row = await sessions.start(
        db_session, tenant.id, user.id, "ordering_food", mode="realtime", locale="zh-CN"
    )
    transcript = Transcript()
    for n, text in enumerate(said):
        transcript.subtitle(Subtitle("learner", f"u{n}", text, final=True))
        transcript.subtitle(Subtitle("tutor", f"a{n}", "Sure, anything else?", final=True))
    maker = app.state.sessionmaker
    await calls.save_lines(maker, app.state.chat_graph, row.conversation_id, transcript.take_all())
    await calls.finish(maker, row.id, seconds)
    return Call(row.id, row.conversation_id)


class Scheduled:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[uuid.UUID, dict[str, Any]]] = []
        monkeypatch.setattr(ReflectionWorker, "schedule", self._schedule)

    def _schedule(self, conversation_id: uuid.UUID, **kwargs: Any) -> None:
        self.calls.append((conversation_id, kwargs))


async def test_a_call_is_reflected_on_and_summed_up(
    app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    summarizer: FakeSummarizer,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await login(client)
    await connect(client, "deepseek")
    reflected = Scheduled(monkeypatch)
    call = await a_call(
        app, db_session, seconds=95, said=["I wants a coffee.", "Just give me a muffin too."]
    )
    # Hung up, summary to come: not `done` yet, and the API won't end it twice.
    db_session.expire_all()
    waiting = await db_session.get(SpeakingSession, call.id)
    assert waiting is not None and (waiting.status, waiting.summary) == ("active", None)

    app.state.after_call.schedule(call.id, language="Chinese")
    await app.state.after_call.wait_idle()

    assert reflected.calls == [(call.conversation_id, {"finish": True, "language": "Chinese"})]
    (prompt,) = summarizer.prompts
    assert "I wants a coffee." in prompt and "Sure, anything else?" in prompt
    db_session.expire_all()
    done = await db_session.get(SpeakingSession, call.id)
    assert done is not None and done.status == "done" and done.summary is not None
    # Quotes are checked against what the learner said (the made-up one is dropped).
    assert [m["quote"] for m in done.summary["mistakes"]] == ["I wants"]
    assert (done.intelligibility, done.turns, done.spoken_turns) == ("mostly", 2, 2)
    assert done.spoken_seconds == done.call_seconds == 95

    detail = (await client.get(f"/speaking/sessions/{call.id}")).json()
    assert (detail["mode"], detail["status"]) == ("realtime", "done")
    page = (await client.get("/speaking/sessions")).json()
    assert [item["id"] for item in page["items"]] == [str(call.id)]


async def test_short_calls_get_no_summary_and_nothing_said_none_either(
    app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    summarizer: FakeSummarizer,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await login(client)
    await connect(client, "deepseek")
    Scheduled(monkeypatch)
    short = await a_call(app, db_session, seconds=20, said=["Hi, I wants a coffee."])
    silent = await a_call(app, db_session, seconds=120, said=[])
    for row in (short, silent):
        app.state.after_call.schedule(row.id)
    await app.state.after_call.wait_idle()

    assert summarizer.prompts == []  # Q61g: no model called
    db_session.expire_all()
    for row in (short, silent):
        found = await db_session.get(SpeakingSession, row.id)
        assert found is not None and (found.status, found.summary) == ("done", None)


async def test_without_a_model_it_fails_and_ending_again_retries(
    app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    summarizer: FakeSummarizer,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await login(client)
    Scheduled(monkeypatch)
    call = await a_call(app, db_session, seconds=60, said=["I wants a coffee."])
    app.state.after_call.schedule(call.id)
    await app.state.after_call.wait_idle()
    db_session.expire_all()
    failed = await db_session.get(SpeakingSession, call.id)
    assert failed is not None and failed.status == "failed"

    await connect(client, "deepseek")
    retried = await client.post(f"/speaking/sessions/{call.id}/end")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "done" and retried.json()["summary"] is not None


async def test_a_call_still_going_cannot_be_ended_through_the_api(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    user = await db_session.scalar(select(User))
    tenant = await db_session.scalar(select(Tenant))
    assert user is not None and tenant is not None
    row = await sessions.start(db_session, tenant.id, user.id, None, mode="realtime")
    response = await client.post(f"/speaking/sessions/{row.id}/end")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "realtime_call"


async def test_every_learner_line_of_a_call_counts_as_spoken(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    """Q61i: short turns give no mistakes, as with recordings (ADR 0029 §4)."""
    await login(client)
    call = await a_call(app, db_session, seconds=60, said=["Me go.", "I goes to the shop daily."])
    state = await app.state.chat_graph.aget_state(
        {"configurable": {"thread_id": str(call.conversation_id)}}
    )
    learner = [m for m in state.values["messages"] if m.type == "human"]
    texts = {m.id: m.text for m in learner}
    items = [
        ChatEvidence(message_id=m.id, kc_id="present_simple", correct=False, error_type="form")
        for m in learner
    ]
    kept = await kept_evidence(db_session, call.conversation_id, items, texts, get_rules())
    assert [item.message_id for item in kept] == [learner[1].id]
