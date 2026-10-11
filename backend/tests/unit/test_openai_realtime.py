"""The openai_realtime adapter against an in-process vendor, in both spellings (ADR 0030 §2)."""

import base64
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.providers import openai_realtime
from app.providers.config import ResolvedModel
from app.providers.openai_realtime import (
    AudioOut,
    RealtimeConnectError,
    RealtimeEvent,
    RealtimeSession,
    ResponseDone,
    SpeechStarted,
    Subtitle,
    ToolCall,
    ToolCalls,
    Usage,
    VendorError,
    open_session,
)
from app.providers.realtime import RealtimeTarget, realtime_target
from tests.fake_realtime_vendor import FakeVendor, fake_vendor

TOOLS = [
    {
        "name": "lookup_word",
        "description": "Look a word up",
        "parameters": {"type": "object", "properties": {"word": {"type": "string"}}},
    }
]


@pytest.fixture(autouse=True)
def local_vendors_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(provider_allow_private_networks=True)
    monkeypatch.setattr(openai_realtime, "get_settings", lambda: settings)


def target(
    vendor: FakeVendor, dialect: str, *, base_url: str = "https://api.openai.com/v1"
) -> RealtimeTarget:
    """The real vendor's target (spelling, rates, voice), reached at the fake's address."""
    real = realtime_target(
        ResolvedModel(
            connection="c",
            kind="openai_compatible",
            model="m-realtime",
            base_url=base_url,
            api_key=SecretStr("sk-realtime-key"),
            params={"realtime_dialect": dialect, "timeout": 5},
        )
    )
    return replace(real, url=f"{vendor.url}?model=m-realtime")


async def collect(call: RealtimeSession, count: int) -> list[RealtimeEvent]:
    events: list[RealtimeEvent] = []
    async for event in call.events():
        events.append(event)
        if len(events) == count:
            break
    return events


async def test_ga_session_and_events() -> None:
    async with fake_vendor() as vendor:
        audio = base64.b64encode(b"\x01\x02" * 4).decode()
        vendor.on(
            "input_audio_buffer.append",
            {"type": "input_audio_buffer.speech_started"},
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "item_id": "u1",
                "delta": "Hel",
            },
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "u1",
                "transcript": "Hello",
            },
            {"type": "response.output_audio.delta", "item_id": "a1", "delta": audio},
            {"type": "response.output_audio_transcript.delta", "item_id": "a1", "delta": "Hi"},
            {
                "type": "response.output_audio_transcript.done",
                "item_id": "a1",
                "transcript": "Hi there.",
            },
            {"type": "response.unknown_thing", "x": 1},
            {
                "type": "response.done",
                "response": {
                    "status": "completed",
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 80,
                        "input_token_details": {"audio_tokens": 100, "text_tokens": 20},
                        "output_token_details": {"audio_tokens": 70, "text_tokens": 10},
                    },
                },
            },
        )
        call = await open_session(target(vendor, "ga"), instructions="Be kind.", tools=TOOLS)
        async with call:
            await call.send_audio(b"\x00\x01" * 10)
            events = await collect(call, 7)

        settings = vendor.of_type("session.update")[0]["session"]
        assert settings["type"] == "realtime"
        assert settings["instructions"] == "Be kind."
        assert settings["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24_000}
        assert settings["audio"]["input"]["turn_detection"]["type"] == "server_vad"
        assert settings["audio"]["input"]["transcription"] == {"model": "gpt-transcribe"}
        assert settings["audio"]["output"]["voice"] == "marin"
        assert settings["tools"] == [{"type": "function", **TOOLS[0]}]
        assert vendor.headers[0]["authorization"] == "Bearer sk-realtime-key"
        (append,) = vendor.of_type("input_audio_buffer.append")
        assert base64.b64decode(append["audio"]) == b"\x00\x01" * 10

    assert events == [
        SpeechStarted(),
        Subtitle("learner", "u1", "Hel", final=False),
        Subtitle("learner", "u1", "Hello", final=True),
        AudioOut(b"\x01\x02" * 4),
        Subtitle("tutor", "a1", "Hi", final=False),
        Subtitle("tutor", "a1", "Hi there.", final=True),
        ResponseDone("completed", Usage(120, 80, 100, 70)),
    ]


async def test_beta_session_for_qwen_and_its_event_names() -> None:
    async with fake_vendor() as vendor:
        vendor.on(
            "input_audio_buffer.append",
            {
                "type": "response.audio.delta",
                "item_id": "a1",
                "delta": base64.b64encode(b"ab").decode(),
            },
            {"type": "response.audio_transcript.delta", "item_id": "a1", "delta": "Hi"},
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "item_id": "u1",
                "text": "Hel",
                "stash": "lo",
            },
            {
                "type": "response.done",
                "response": {
                    "status": "completed",
                    "usage": {
                        "input_tokens": 9,
                        "output_tokens": 4,
                        "input_tokens_details": {"audio_tokens": 7},
                    },
                },
            },
        )
        qwen = target(vendor, "beta", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert qwen.input_rate == 16_000
        async with await open_session(qwen, instructions="Hi", tools=[]) as call:
            await call.send_audio(b"\x00\x00")
            events = await collect(call, 4)
            await call.interrupt(played_ms=500)

        settings = vendor.of_type("session.update")[0]["session"]
        assert settings["modalities"] == ["text", "audio"]
        assert (settings["input_audio_format"], settings["output_audio_format"]) == ("pcm", "pcm")
        assert settings["input_audio_transcription"] == {"model": "qwen3-asr-flash-realtime"}
        assert settings["turn_detection"]["type"] == "server_vad"
        assert "tools" not in settings and "voice" not in settings

    assert events == [
        AudioOut(b"ab"),
        Subtitle("tutor", "a1", "Hi", final=False),
        Subtitle("learner", "u1", "Hel", final=False),
        ResponseDone("completed", Usage(9, 4, 7, 0)),
    ]
    # The older spelling has no truncate: cancelling is all it can do.
    assert vendor.of_type("response.cancel")
    assert not vendor.of_type("conversation.item.truncate")


async def test_interrupting_ga_forgets_what_was_not_heard() -> None:
    async with fake_vendor() as vendor:
        vendor.on(
            "input_audio_buffer.append",
            {
                "type": "response.output_audio.delta",
                "item_id": "a7",
                "delta": base64.b64encode(b"x").decode(),
            },
        )
        async with await open_session(target(vendor, "ga"), instructions="") as call:
            await call.send_audio(b"\x00\x00")
            await collect(call, 1)
            await call.interrupt(played_ms=1200)
            await call.respond("Say goodbye briefly.")
            await call.send_tool_results([("call_1", json.dumps({"ok": True})), ("call_2", "{}")])
            await call.close()

    (truncate,) = vendor.of_type("conversation.item.truncate")
    assert (truncate["item_id"], truncate["audio_end_ms"]) == ("a7", 1200)
    creates = vendor.of_type("response.create")
    assert creates[0]["response"] == {"instructions": "Say goodbye briefly."}
    output, second = vendor.of_type("conversation.item.create")
    assert output["item"] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"ok": true}',
    }
    assert second["item"]["call_id"] == "call_2"
    # Both results, then one reply.
    assert creates[1:] == [{"type": "response.create"}]


async def test_tool_calls_once_and_untrusted_messages_dropped() -> None:
    async with fake_vendor() as vendor:
        call_item = {
            "type": "function_call",
            "call_id": "c1",
            "name": "lookup_word",
            "arguments": '{"word":"cat"}',
        }
        vendor.on(
            "input_audio_buffer.append",
            {
                "type": "response.function_call_arguments.done",
                "call_id": "c1",
                "arguments": '{"word":"cat"}',
            },
            {"type": "response.output_item.done", "item": call_item},
            {"type": "response.function_call_arguments.done", **call_item},
            {"type": "response.output_audio.delta", "delta": "%%% not base64"},
            {"type": "response.output_audio_transcript.delta", "delta": "no item id"},
            {"type": "error", "error": {"type": "invalid_request_error", "message": "x" * 900}},
            {
                "type": "response.output_item.done",
                "item": {**call_item, "call_id": "c2", "name": "end_session", "arguments": None},
            },
            {"type": "response.done", "response": {"status": "completed"}},
        )
        async with await open_session(target(vendor, "ga"), instructions="") as call:
            await vendor.push({"type": "response.done"})  # before anything: no usage, no crash
            await call.send_audio(b"\x00\x00")
            events = await collect(call, 4)

    assert events[0] == ResponseDone("", None)
    assert isinstance(events[1], VendorError)
    assert events[1].code == "invalid_request_error"
    assert len(events[1].message) == 500
    # A reply's calls come together, after it is done.
    assert events[2] == ResponseDone("completed", None)
    assert events[3] == ToolCalls(
        (ToolCall("c1", "lookup_word", '{"word":"cat"}'), ToolCall("c2", "end_session", "{}"))
    )


async def test_connect_failures_are_reported_for_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async with fake_vendor() as vendor:
        vendor.refuse = True
        with pytest.raises(RealtimeConnectError, match="bad key"):
            await open_session(target(vendor, "ga"), instructions="")
        unreachable = target(vendor, "ga")
        dead = vendor.url.replace(vendor.url.split(":")[2].split("/")[0], "1")
    with pytest.raises(RealtimeConnectError):
        await open_session(_with_url(unreachable, dead), instructions="")

    # Without private networks allowed, a local address is refused before connecting.
    monkeypatch.setattr(
        openai_realtime,
        "get_settings",
        lambda: SimpleNamespace(provider_allow_private_networks=False),
    )
    async with fake_vendor() as vendor:
        with pytest.raises(RealtimeConnectError, match="not allowed"):
            await open_session(target(vendor, "ga"), instructions="")
        assert vendor.received == []


def _with_url(original: RealtimeTarget, url: str) -> RealtimeTarget:
    return replace(original, url=url)
