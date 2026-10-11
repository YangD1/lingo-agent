"""The realtime relay end to end (ADR 0030, task 60.3): a real server, a browser-like
WebSocket client and the in-process fake vendor."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus

from app.adaptive.rules import get_rules
from app.api import realtime as realtime_api
from app.chat.service import thread_config
from app.credentials import service
from app.credentials.crypto import get_keyring
from app.db.models import (
    Conversation,
    SpeakingSession,
    Tenant,
    TenantMember,
    User,
    UserCard,
    Word,
)
from app.deps import AUTH_COOKIE
from app.providers import realtime_session
from app.providers.llm import get_providers_config
from app.realtime import calls, relay
from app.realtime import tools as realtime_tools
from app.realtime.limits import CallLimit, day_start
from app.speaking import sessions
from app.speaking.scenarios import get_scenarios
from app.usage import recorder as usage_recorder
from app.usage.recorder import UsageRecord
from tests.fake_gemini_vendor import fake_gemini, heard, said, turn_complete
from tests.fake_realtime_vendor import FakeVendor, fake_vendor


@pytest.fixture(autouse=True)
def local_vendors(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(provider_allow_private_networks=True)
    monkeypatch.setattr(realtime_session, "get_settings", lambda: settings)


@pytest.fixture
def usage_records() -> Iterator[list[UsageRecord]]:
    records: list[UsageRecord] = []
    usage_recorder.set_usage_sink(records.append)
    yield records
    usage_recorder.set_usage_sink(None)


@pytest.fixture
async def server(app: FastAPI) -> AsyncIterator[str]:
    """The app on a real port: the relay needs a real WebSocket."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    while not srv.started:  # noqa: ASYNC110 (uvicorn offers no event to wait on)
        await asyncio.sleep(0.01)
    port = srv.servers[0].sockets[0].getsockname()[1]
    yield f"127.0.0.1:{port}"
    srv.should_exit = True
    await task


async def sign_up(client: AsyncClient, email: str = "caller@example.com") -> str:
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    token = client.cookies.get(AUTH_COOKIE)
    assert token
    return token


async def add_vendor(
    db_session: AsyncSession, client: AsyncClient, name: str, vendor: FakeVendor
) -> None:
    """A connection the realtime route reaches the fake at; `kind=openai` on an unknown
    host speaks OpenAI's current spelling at 24 kHz."""
    tenant_id = await db_session.scalar(select(TenantMember.tenant_id).limit(1))
    assert tenant_id is not None
    await service.create_connection(
        db_session,
        tenant_id=tenant_id,
        config=get_providers_config(),
        keyring=get_keyring(),
        allow_private=True,
        preset=None,
        name=name,
        kind="openai",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("sk-test-realtime-key"),
        params=service.CallParams(realtime_url=vendor.url),
    )


async def set_route(client: AsyncClient, *refs: str) -> None:
    response = await client.put("/tenant/routes/realtime/default", json={"models": list(refs)})
    assert response.status_code == 200, response.text


def dial(host: str, token: str, *, query: str = "", origin: str | None = None) -> Any:
    return connect(
        f"ws://{host}/speech/realtime{query}",
        additional_headers={"Cookie": f"{AUTH_COOKIE}={token}"},
        origin=origin or f"http://{host}",  # type: ignore[arg-type]
        compression=None,
    )


async def next_json(ws: ClientConnection) -> dict[str, Any]:
    while True:
        message = await asyncio.wait_for(ws.recv(), 5)
        if isinstance(message, str):
            data: dict[str, Any] = json.loads(message)
            return data


async def until(ws: ClientConnection, kind: str) -> dict[str, Any]:
    while (event := await next_json(ws))["type"] != kind:
        pass
    return event


async def test_a_call_relays_audio_subtitles_and_usage(
    app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    server: str,
    usage_records: list[UsageRecord],
) -> None:
    token = await sign_up(client)
    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        await set_route(client, "voice:gpt-realtime-2.1")
        reply = base64.b64encode(b"\x10\x00" * 240).decode()
        vendor.on(
            "input_audio_buffer.append",
            {"type": "input_audio_buffer.speech_started"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "u1",
                "transcript": "Hello there",
            },
            {"type": "response.output_audio.delta", "item_id": "a1", "delta": reply},
            {"type": "response.output_audio_transcript.done", "item_id": "a1", "transcript": "Hi!"},
            {
                "type": "response.done",
                "response": {
                    "status": "completed",
                    "usage": {"input_tokens": 50, "output_tokens": 30},
                },
            },
        )
        async with dial(server, token, query="?scenario=self_intro") as ws:
            ready = await next_json(ws)
            assert ready["type"] == "ready"
            assert (ready["input_rate"], ready["output_rate"]) == (24_000, 24_000)
            assert ready["limit_seconds"] == 900
            await ws.send(b"\x00\x00" * 2400)  # 0.1 s of learner audio
            assert await next_json(ws) == {"type": "speech_started"}
            learner = await next_json(ws)
            assert (learner["role"], learner["text"], learner["final"]) == (
                "learner",
                "Hello there",
                True,
            )
            audio = await asyncio.wait_for(ws.recv(), 5)
            assert audio == b"\x10\x00" * 240
            tutor = await next_json(ws)
            assert (tutor["role"], tutor["text"]) == ("tutor", "Hi!")
            assert await next_json(ws) == {"type": "response_done"}
            await ws.send(json.dumps({"type": "end"}))
            assert await until(ws, "ended") == {"type": "ended", "reason": "hangup"}

        settings = vendor.of_type("session.update")[0]["session"]
        intro = get_scenarios().get("self_intro")
        assert intro is not None and intro.opening in settings["instructions"]
        # The tutor speaks first, as the instructions say (Q58e).
        assert vendor.received[1] == {"type": "response.create"}
        assert vendor.headers[0]["authorization"] == "Bearer sk-test-realtime-key"
        (append,) = vendor.of_type("input_audio_buffer.append")
        assert base64.b64decode(append["audio"]) == b"\x00\x00" * 2400

    (usage,) = [r for r in usage_records if r.task == "realtime"]
    assert (usage.input_tokens, usage.output_tokens, usage.status) == (50, 30, "ok")
    assert usage.audio_seconds == 0.1
    assert (usage.connection_name, usage.model, usage.is_fallback) == (
        "voice",
        "gpt-realtime-2.1",
        False,
    )
    # Under 30 s: done without a summary (Q61g).
    await app.state.after_call.wait_idle()
    db_session.expire_all()
    row = await db_session.scalar(select(SpeakingSession))
    assert row is not None
    assert (row.mode, row.status, row.scenario_id) == ("realtime", "done", "self_intro")
    assert row.summary is None
    # The whole call counts as speaking time (Q61h); each learner line is a turn.
    assert row.spoken_seconds == row.call_seconds
    assert (row.turns, row.spoken_turns) == (1, 1)
    assert row.ended_at is not None and row.call_seconds > 0
    conversation = await db_session.get(Conversation, row.conversation_id)
    assert conversation is not None and conversation.purpose == "realtime"
    assert usage.conversation_id == row.conversation_id
    # Nobody types into a call's conversation.
    typed = await client.post(
        f"/conversations/{row.conversation_id}/messages", json={"content": "hi"}
    )
    assert typed.status_code == 409
    assert typed.json()["detail"]["code"] == "realtime_call"


async def test_falls_back_when_connecting_only(
    client: AsyncClient,
    db_session: AsyncSession,
    server: str,
    usage_records: list[UsageRecord],
) -> None:
    token = await sign_up(client)
    async with fake_vendor() as broken, fake_vendor() as working:
        broken.refuse = True
        await add_vendor(db_session, client, "first", broken)
        await add_vendor(db_session, client, "second", working)
        await set_route(client, "first:gpt-realtime-2.1", "second:gpt-realtime-2.1")
        working.on(
            "input_audio_buffer.append",
            {"type": "response.done", "response": {"status": "completed"}},
        )
        async with dial(server, token) as ws:
            assert (await next_json(ws))["type"] == "ready"
            await ws.send(b"\x00\x00" * 100)
            await until(ws, "response_done")
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, "ended")

    failed, answered = (r for r in usage_records if r.task == "realtime")
    assert (failed.connection_name, failed.status, failed.is_fallback) == ("first", "error", False)
    assert (answered.connection_name, answered.status, answered.is_fallback) == (
        "second",
        "ok",
        True,
    )
    # A vendor without usage still leaves a row with the audio it was sent.
    assert (answered.input_tokens, answered.audio_seconds) == (0, round(200 / 48_000, 2))


async def test_refusals_before_the_call(
    client: AsyncClient, db_session: AsyncSession, server: str
) -> None:
    token = await sign_up(client)
    # Another site's page can't open a call with the learner's cookie.
    with pytest.raises(InvalidStatus) as caught:
        async with dial(server, token, origin="https://evil.example.com"):
            pass
    assert caught.value.response.status_code == 403
    with pytest.raises(InvalidStatus):
        async with dial(server, "not-a-token"):
            pass

    async with dial(server, token) as ws:
        assert await next_json(ws) == {
            "type": "ended",
            "reason": "refused",
            "code": "no_realtime_model",
        }
    # Behind the frontend's proxy the browser's host comes as X-Forwarded-Host (checked
    # with `next dev`, 2026-10-10).
    async with connect(
        f"ws://{server}/speech/realtime",
        additional_headers={
            "Cookie": f"{AUTH_COOKIE}={token}",
            "X-Forwarded-Host": "localhost:3000",
        },
        origin="http://localhost:3000",  # type: ignore[arg-type]
    ) as ws:
        assert (await next_json(ws))["code"] == "no_realtime_model"
    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        await set_route(client, "voice:gpt-realtime-2.1")
        async with dial(server, token, query="?scenario=no_such_thing") as ws:
            assert (await next_json(ws))["code"] == "unknown_scenario"
        vendor.refuse = True
        async with dial(server, token) as ws:
            assert (await next_json(ws))["code"] == "realtime_unavailable"
    assert await db_session.scalar(select(SpeakingSession)) is None


async def test_browser_messages_are_white_listed_and_metered(
    client: AsyncClient, db_session: AsyncSession, server: str
) -> None:
    token = await sign_up(client)
    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        await set_route(client, "voice:gpt-realtime-2.1")
        async with dial(server, token) as ws:
            await next_json(ws)
            await ws.send(json.dumps({"type": "session.update", "session": {"instructions": "x"}}))
            await ws.send("not json")
            await ws.send(b"\x00")  # half a sample
            await ws.send(b"\x00\x00" * 40_000)  # over the frame limit
            # Ten seconds of audio at once: only about two seconds' burst gets through.
            for _ in range(20):
                await ws.send(b"\x00\x00" * 12_000)
            await ws.send(json.dumps({"type": "interrupt", "played_ms": 800}))
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, "ended")

    assert len(vendor.of_type("session.update")) == 1  # the backend's own only
    appended = sum(
        len(base64.b64decode(e["audio"])) for e in vendor.of_type("input_audio_buffer.append")
    )
    assert 0 < appended <= 3 * 48_000
    assert vendor.of_type("response.cancel")


def short_calls(monkeypatch: pytest.MonkeyPatch, seconds: int) -> None:
    """Calls this long, without waiting the minute a real limit needs."""

    async def limit(*_: Any) -> CallLimit:
        return CallLimit(15, 30, 0.0, "ok", seconds)

    monkeypatch.setattr(realtime_api, "call_limit", limit)


async def test_time_warning_goodbye_and_shutdown_end_calls(
    client: AsyncClient,
    db_session: AsyncSession,
    server: str,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await sign_up(client)
    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        await set_route(client, "voice:gpt-realtime-2.1")
        vendor.on("response.create", {"type": "response.done", "response": {"status": "completed"}})
        short_calls(monkeypatch, 2)
        monkeypatch.setattr(relay, "WARNING_SECONDS", 1)
        async with dial(server, token) as ws:
            assert (await next_json(ws))["limit_seconds"] == 2
            assert await until(ws, "time_warning") == {
                "type": "time_warning",
                "remaining_seconds": 1,
            }
            assert await next_json(ws) == {"type": "wrapping_up"}
            await ws.send(b"\x00\x00" * 2400)  # ignored: it would cut the goodbye short
            assert await next_json(ws) == {"type": "response_done"}
            assert await next_json(ws) == {"type": "ended", "reason": "time_limit"}
        opening, goodbye = vendor.of_type("response.create")
        assert "response" not in opening
        assert "goodbye" in goodbye["response"]["instructions"]
        assert not vendor.of_type("input_audio_buffer.append")

        # A vendor that never says goodbye is cut off anyway.
        vendor.script.clear()
        monkeypatch.setattr(relay, "WRAP_UP_SECONDS", 1)
        short_calls(monkeypatch, 1)
        async with dial(server, token) as ws:
            await until(ws, "wrapping_up")
            assert await next_json(ws) == {"type": "ended", "reason": "time_limit"}

        short_calls(monkeypatch, 600)
        async with dial(server, token) as ws:
            await next_json(ws)
            assert len(app.state.realtime_calls) == 1
            await app.state.realtime_calls.stop_all()
            assert await until(ws, "ended") == {"type": "ended", "reason": "server_stopping"}
        assert len(app.state.realtime_calls) == 0

    await app.state.after_call.wait_idle()
    db_session.expire_all()
    rows = (await db_session.scalars(select(SpeakingSession))).all()
    assert [r.status for r in rows] == ["done", "done", "done"]


async def test_tenant_limits_decide_how_long_a_call_may_last(
    client: AsyncClient, db_session: AsyncSession, server: str
) -> None:
    token = await sign_up(client)
    user = await db_session.scalar(select(User))
    tenant = await db_session.scalar(select(Tenant))
    assert user is not None and tenant is not None

    async def refused() -> str | None:
        async with dial(server, token) as ws:
            event = await next_json(ws)
            return event.get("code")

    limits = await client.get("/tenant/realtime")
    assert limits.json() == {
        "session_minutes": 15,
        "daily_minutes": 30,
        "used_minutes": 0.0,
        "state": "ok",
    }
    for bad in (
        {"session_minutes": -1, "daily_minutes": 30},
        {"session_minutes": 61, "daily_minutes": 30},
    ):
        assert (await client.put("/tenant/realtime", json=bad)).status_code == 422

    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        await set_route(client, "voice:gpt-realtime-2.1")
        # 25 of today's 30 minutes used (yesterday's call doesn't count): 5 minutes left.
        for started, seconds in (
            (datetime.now(UTC), 25 * 60),
            (day_start(datetime.now(UTC)) - timedelta(hours=1), 600),
        ):
            row = await sessions.start(db_session, tenant.id, user.id, None, mode="realtime")
            row.started_at, row.call_seconds, row.status = started, seconds, "done"
        await db_session.commit()
        caps = (await client.get("/speech/capabilities")).json()
        assert (caps["realtime"], caps["realtime_minutes_left"]) == (True, 5)
        async with dial(server, token) as ws:
            assert (await next_json(ws))["limit_seconds"] == 300
            # A second call at once would get the same minutes again.
            async with dial(server, token) as second:
                assert (await next_json(second))["code"] == "realtime_busy"
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, "ended")

        put = await client.put(
            "/tenant/realtime", json={"session_minutes": 15, "daily_minutes": 25}
        )
        assert put.status_code == 200
        assert put.json()["state"] == "used_up"
        assert put.json()["used_minutes"] >= 25.0
        assert await refused() == "realtime_used_up"
        caps = (await client.get("/speech/capabilities")).json()
        assert (caps["realtime"], caps["realtime_minutes_left"]) == (True, 0)

        put = await client.put("/tenant/realtime", json={"session_minutes": 0, "daily_minutes": 25})
        assert put.json()["state"] == "off"
        assert await refused() == "realtime_off"
        caps = (await client.get("/speech/capabilities")).json()
        assert (caps["realtime"], caps["realtime_minutes_left"]) == (False, 0)


async def test_capabilities_without_a_realtime_route(client: AsyncClient) -> None:
    await sign_up(client)
    caps = (await client.get("/speech/capabilities")).json()
    assert (caps["realtime"], caps["realtime_minutes_left"]) == (False, 0)


async def test_cut_off_calls_are_closed_and_never_idle(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    await sign_up(client)
    user = await db_session.scalar(select(User))
    tenant = await db_session.scalar(select(Tenant))
    assert user is not None and tenant is not None
    call = await sessions.start(db_session, tenant.id, user.id, None, mode="realtime")
    talk = await sessions.start(db_session, tenant.id, user.id, None)
    call_id, talk_id = call.id, talk.id
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    await db_session.execute(update(Conversation).values(updated_at=long_ago))
    await db_session.commit()

    idle = await sessions.idle_sessions(db_session, user.id, datetime.now(UTC), get_rules())
    assert idle == [talk_id]
    assert await calls.close_orphaned(app.state.sessionmaker) == 1
    db_session.expire_all()
    closed = await db_session.get(SpeakingSession, call_id)
    still = await db_session.get(SpeakingSession, talk_id)
    assert closed is not None and still is not None
    # Ended, waiting for its follow-up, which the start then runs.
    assert (closed.status, still.status) == ("active", "active")
    assert closed.ended_at is not None
    assert await app.state.after_call.recover() == 1
    await app.state.after_call.wait_idle()
    db_session.expire_all()
    closed = await db_session.get(SpeakingSession, call_id)
    assert closed is not None and closed.status == "done"


# --- connection test (task 60.6) ----------------------------------------------------------


async def test_connection_test_opens_a_session_and_hangs_up(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    await sign_up(client)
    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        (conn,) = (await client.get("/tenant/connections")).json()
        url = f"/tenant/connections/{conn['id']}/test"

        # Told from the model's name.
        result = (await client.post(url, json={"model": "gpt-realtime-2.1"})).json()
        assert (result["ok"], result["purpose"]) == (True, "realtime"), result
        assert [e["type"] for e in vendor.received] == ["session.update"]  # no reply asked

        # Any model the realtime route uses is tested as one.
        await set_route(client, "voice:my-voice")
        result = (await client.post(url, json={"model": "my-voice"})).json()
        assert (result["ok"], result["purpose"]) == (True, "realtime"), result

        vendor.refuse = True
        result = (await client.post(url, json={"model": "my-voice"})).json()
        assert (result["ok"], result["purpose"]) == (False, "realtime")
        assert "bad key" in result["error"]


async def test_the_transcript_is_saved_turn_by_turn(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession, server: str
) -> None:
    """Q61e, Q61f: lines in the turns' order although the learner's subtitle comes late;
    a reply talked over keeps what had come, marked; what's left is saved at hang-up."""
    token = await sign_up(client)
    graph = app.state.chat_graph

    async def saved(conversation_id: Any) -> list[Any]:
        state = await graph.aget_state(thread_config(conversation_id))
        return list(state.values.get("messages", []))

    async def saved_at_least(conversation_id: Any, count: int) -> list[Any]:
        """The browser hears `response_done` before the lines are saved."""
        for _ in range(100):
            if len(messages := await saved(conversation_id)) >= count:
                return messages
            await asyncio.sleep(0.02)
        return messages

    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        await set_route(client, "voice:gpt-realtime-2.1")
        vendor.on(
            "input_audio_buffer.append",
            {"type": "input_audio_buffer.speech_started"},
            {"type": "input_audio_buffer.committed", "item_id": "u1"},
            {"type": "response.output_audio_transcript.done", "item_id": "a1", "transcript": "Hi!"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "u1",
                "transcript": "Hello there",
            },
            {"type": "response.done", "response": {"status": "completed"}},
        )
        vendor.on(
            "input_audio_buffer.append",
            {"type": "response.output_audio_transcript.delta", "item_id": "a2", "delta": "Let "},
            {"type": "response.output_audio_transcript.delta", "item_id": "a2", "delta": "me"},
            {"type": "input_audio_buffer.speech_started"},
            {"type": "input_audio_buffer.committed", "item_id": "u2"},
            # Text for the reply after it was talked over isn't what the learner heard.
            {
                "type": "response.output_audio_transcript.done",
                "item_id": "a2",
                "transcript": "Let me tell you a story.",
            },
            {"type": "response.done", "response": {"status": "cancelled"}},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "u2",
                "transcript": "Wait, sorry",
            },
        )
        vendor.on(
            "input_audio_buffer.append",
            {"type": "input_audio_buffer.committed", "item_id": "u3"},  # never transcribed
            {"type": "response.output_audio_transcript.delta", "item_id": "a3", "delta": "Bye"},
            {"type": "response.done", "response": {"status": "completed"}},
        )
        async with dial(server, token) as ws:
            ready = await next_json(ws)
            conversation_id = ready["conversation_id"]
            await ws.send(b"\x00\x00" * 2400)
            await until(ws, "response_done")
            first = await saved_at_least(conversation_id, 2)
            assert [(m.type, m.text) for m in first] == [("human", "Hello there"), ("ai", "Hi!")]
            await ws.send(b"\x00\x00" * 2400)
            await until(ws, "response_done")
            # The reply talked over is saved; u2's subtitle is still to come.
            assert [m.text for m in await saved_at_least(conversation_id, 3)][2:] == ["Let me"]
            await until(ws, "subtitle")
            await ws.send(b"\x00\x00" * 2400)
            await until(ws, "response_done")
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, "ended")

    messages = await saved(conversation_id)
    assert [(m.type, m.text) for m in messages] == [
        ("human", "Hello there"),
        ("ai", "Hi!"),
        ("ai", "Let me"),
        ("human", "Wait, sorry"),
        ("ai", "Bye"),
    ]
    assert all(m.additional_kwargs.get("voice_call") for m in messages)
    assert [bool(m.additional_kwargs.get("interrupted")) for m in messages] == [
        False,
        False,
        True,
        False,
        False,
    ]
    # The call's conversation shows in no chat list but reads like one.
    history = await client.get(f"/conversations/{conversation_id}/messages")
    assert history.status_code == 200
    assert [m["role"] for m in history.json()] == ["user", "assistant", "user", "assistant"]


def function_call(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {
        "type": "response.output_item.done",
        "item": {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments},
    }


async def test_tools_run_for_the_learner_and_show_what_they_did(
    client: AsyncClient, db_session: AsyncSession, server: str
) -> None:
    """ADR 0030 §4, Q61a-d: one reply's calls run together, results go back in one go
    with one reply asked for; failures and calls over the limit are results."""
    token = await sign_up(client)
    db_session.add_all(
        [
            Word(word="ubiquitous", phonetic="ju:'bikwitəs", translation="a. 无所不在的\nadv. x"),
            Word(word="cat", translation="n. 猫"),
        ]
    )
    await db_session.commit()
    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        await set_route(client, "voice:gpt-realtime-2.1")
        vendor.on(
            "input_audio_buffer.append",
            {"type": "input_audio_buffer.committed", "item_id": "u1"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "u1",
                "transcript": "What does ubiquitous mean? Keep it for me.",
            },
            function_call("c1", "lookup_word", '{"word": "Ubiquitous"}'),
            function_call("c2", "add_to_vocab", '{"word": "ubiquitous"}'),
            function_call("c3", "add_to_vocab", '{"user_id": "someone else"}'),
            function_call("c4", "end_session", "{}"),  # over 3 per reply
            {"type": "response.done", "response": {"status": "completed"}},
        )
        vendor.on(
            "input_audio_buffer.append",
            function_call("c5", "add_to_vocab", '{"word": "ubiquitous"}'),
            function_call("c6", "transfer_money", "{}"),
            function_call("c7", "end_session", "{}"),
            {"type": "response.done", "response": {"status": "completed"}},
        )
        async with dial(server, token) as ws:
            ready = await next_json(ws)
            await ws.send(b"\x00\x00" * 2400)
            shown = [await until(ws, "tool") for _ in range(4)]
            await ws.send(b"\x00\x00" * 2400)
            shown += [await until(ws, "tool") for _ in range(2)]
            assert await next_json(ws) == {"type": "end_suggested"}
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, "ended")

    outputs = {
        e["item"]["call_id"]: json.loads(e["item"]["output"])
        for e in vendor.of_type("conversation.item.create")
    }
    assert outputs["c1"] == {
        "word": "ubiquitous",
        "phonetic": "ju:'bikwitəs",
        "meanings": ["a. 无所不在的", "adv. x"],
        "on_word_list": False,
    }
    assert outputs["c2"] == {"word": "ubiquitous", "status": "added"}
    assert "error" in outputs["c3"]  # the learner is the caller, not an argument
    assert outputs["c4"] == {"error": "too many tool calls"}
    assert outputs["c5"] == {"word": "ubiquitous", "status": "existing"}
    assert outputs["c6"] == {"error": "unknown tool"}
    assert outputs["c7"]["ok"] is True
    # Each batch of results, then one reply: the opening, plus one per batch.
    assert len(vendor.of_type("response.create")) == 3

    learner_turn = next(m for m in shown if m["call_id"] == "c1")["turn_id"]
    assert [(m["name"], m["call_id"], m["status"], m["kind"]) for m in shown] == [
        ("lookup_word", "c1", "ok", "tool"),
        ("add_to_vocab", "c2", "ok", "tool"),
        ("add_to_vocab", "c3", "failed", "tool"),
        ("end_session", "c4", "failed", "tool"),
        ("add_to_vocab", "c5", "ok", "tool"),
        ("end_session", "c7", "ok", "tool"),
    ]
    assert shown[1]["summary"]["added"][0]["word"] == "ubiquitous"
    assert shown[4]["summary"]["existing"][0]["word"] == "ubiquitous"
    assert shown[2]["summary"] == shown[3]["summary"] == {}  # failures say nothing more
    assert all(m["turn_id"] == learner_turn for m in shown)
    # Kept under the learner's message in the call's conversation.
    activity = await client.get(f"/conversations/{ready['conversation_id']}/activity")
    assert activity.status_code == 200, activity.text
    body = activity.json()
    calls = [a["call_id"] for a in body["activities"] if a["turn_id"] == learner_turn]
    assert sorted(calls) == ["c1", "c2", "c3", "c4", "c5", "c7"]
    history = await client.get(f"/conversations/{ready['conversation_id']}/messages")
    assert history.json()[0]["id"] == learner_turn
    card = await db_session.scalar(select(UserCard).join(Word).where(Word.word == "ubiquitous"))
    assert card is not None and card.source == "auto"
    assert body["words_on_list"] == [card.word_id]


async def test_a_slow_tool_is_a_timeout_result(
    client: AsyncClient, db_session: AsyncSession, server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await sign_up(client)

    async def stuck(*_: Any) -> Any:
        await asyncio.sleep(30)

    monkeypatch.setattr(relay, "TOOL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(realtime_tools.CallTools, "run", stuck)
    async with fake_vendor() as vendor:
        await add_vendor(db_session, client, "voice", vendor)
        await set_route(client, "voice:gpt-realtime-2.1")
        vendor.on(
            "input_audio_buffer.append",
            function_call("c1", "lookup_word", '{"word": "cat"}'),
            {"type": "response.done", "response": {"status": "completed"}},
        )
        async with dial(server, token) as ws:
            await next_json(ws)
            await ws.send(b"\x00\x00" * 2400)
            shown = await until(ws, "tool")
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, "ended")

    assert (shown["name"], shown["status"]) == ("lookup_word", "failed")
    (result,) = vendor.of_type("conversation.item.create")
    assert json.loads(result["item"]["output"]) == {"error": "timed out"}


async def test_a_gemini_call_and_its_connection_test(
    client: AsyncClient, db_session: AsyncSession, server: str
) -> None:
    """Gemini Live behind the same relay (61.5): 16 kHz in, the tutor first, tool
    results sent back without asking for a reply, the transcript in turn order."""
    token = await sign_up(client)
    tenant_id = await db_session.scalar(select(TenantMember.tenant_id).limit(1))
    assert tenant_id is not None
    async with fake_gemini() as vendor:
        await service.create_connection(
            db_session,
            tenant_id=tenant_id,
            config=get_providers_config(),
            keyring=get_keyring(),
            allow_private=True,
            preset=None,
            name="gem",
            kind="gemini",
            base_url="https://generativelanguage.googleapis.com",
            api_key=SecretStr("AIza-test-key"),
            params=service.CallParams(realtime_url=vendor.url),
        )
        (conn,) = (await client.get("/tenant/connections")).json()
        tested = await client.post(
            f"/tenant/connections/{conn['id']}/test", json={"model": "gemini-3.8-live"}
        )
        assert (tested.json()["ok"], tested.json()["purpose"]) == (True, "realtime"), tested.text
        assert [next(iter(m)) for m in vendor.received] == ["setup"]  # no reply asked
        vendor.received.clear()

        await set_route(client, "gem:gemini-3.8-live")
        vendor.on("clientContent", said("Hello!"), turn_complete(40, 10))
        vendor.on(
            "realtimeInput",
            heard("Bye now."),
            {"toolCall": {"functionCalls": [{"id": "c1", "name": "end_session", "args": {}}]}},
        )
        vendor.on("realtimeInput")  # later audio: no answer
        vendor.on("toolResponse", said("Goodbye!"), turn_complete(60, 8))
        async with dial(server, token) as ws:
            ready = await next_json(ws)
            assert (ready["input_rate"], ready["output_rate"]) == (16_000, 24_000)
            tutor = await until(ws, "subtitle")
            assert (tutor["role"], tutor["text"], tutor["final"]) == ("tutor", "Hello!", False)
            await until(ws, "response_done")
            await ws.send(b"\x00\x00" * 1600)
            tool = await until(ws, "tool")
            assert (tool["name"], tool["status"]) == ("end_session", "ok")
            assert await next_json(ws) == {"type": "end_suggested"}
            await until(ws, "response_done")
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, "ended")

    (response,) = vendor.of_kind("toolResponse")
    assert response["functionResponses"][0]["id"] == "c1"
    assert response["functionResponses"][0]["response"]["ok"] is True
    # The opening cue only: the model goes on by itself after tool results.
    assert len(vendor.of_kind("clientContent")) == 1
    history = await client.get(f"/conversations/{ready['conversation_id']}/messages")
    assert [(m["role"], m["content"]) for m in history.json()] == [
        ("assistant", "Hello!"),
        ("user", "Bye now."),
        ("assistant", "Goodbye!"),
    ]
