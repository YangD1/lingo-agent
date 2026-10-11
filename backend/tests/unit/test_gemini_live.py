"""The gemini_live adapter against an in-process Gemini Live server (ADR 0030 §2)."""

import asyncio
import base64
import json
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from app.providers import realtime_session
from app.providers.config import ResolvedModel
from app.providers.gemini_live import START_CUE
from app.providers.realtime import RealtimeTarget, realtime_target
from app.providers.realtime_session import (
    AudioOut,
    LearnerTurn,
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
from tests.fake_gemini_vendor import FakeGemini, audio, fake_gemini, heard, said, turn_complete

KEY = "AIza-secret-key"
TOOLS = [
    {
        "name": "lookup_word",
        "description": "Look a word up",
        "parameters": {
            "type": "object",
            "properties": {"word": {"type": "string", "description": "The word."}},
            "required": ["word"],
        },
    },
    {"name": "end_session", "description": "Hang up", "parameters": {"type": "object"}},
]


@pytest.fixture(autouse=True)
def local_vendors_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(provider_allow_private_networks=True)
    monkeypatch.setattr(realtime_session, "get_settings", lambda: settings)


def target(vendor: FakeGemini) -> RealtimeTarget:
    real = realtime_target(
        ResolvedModel(
            connection="g",
            kind="gemini",
            model="gemini-3.8-live",
            base_url="https://generativelanguage.googleapis.com",
            api_key=SecretStr(KEY),
            params={"timeout": 5},
        )
    )
    return replace(real, url=vendor.url)


async def collect(call: RealtimeSession, count: int) -> list[RealtimeEvent]:
    events: list[RealtimeEvent] = []
    async with asyncio.timeout(5):
        async for event in call.events():
            events.append(event)
            if len(events) == count:
                break
    return events


async def eventually(check: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not check():  # noqa: ASYNC110 (the fake server offers no event to wait on)
            await asyncio.sleep(0.01)


async def until_received(vendor: FakeGemini, kind: str, count: int = 1) -> list[Any]:
    await eventually(lambda: len(vendor.of_kind(kind)) >= count)
    return vendor.of_kind(kind)


async def test_setup_turns_and_subtitles() -> None:
    async with fake_gemini() as vendor:
        vendor.on(
            "clientContent",
            said("Hi "),
            audio(b"\x01\x00" * 4),
            said("there!"),
            turn_complete(100, 20),
        )
        call = await open_session(target(vendor), instructions="Be kind.", tools=TOOLS)
        async with call:
            assert call.target.input_rate == 16_000
            await call.respond()
            assert await collect(call, 5) == [
                Subtitle("tutor", "g1", "Hi ", False),
                AudioOut(b"\x01\x00" * 4),
                Subtitle("tutor", "g1", "there!", False),
                Subtitle("tutor", "g1", "Hi there!", True),
                ResponseDone("completed", Usage(100, 20, 50, 20)),
            ]
            await call.send_audio(b"\x00\x00" * 160)
            # The learner's transcript runs late: it is theirs until the turn is over.
            await vendor.push(
                heard("I like"),
                audio(b"\x02\x00"),
                heard(" cats."),
                {"serverContent": {"turnComplete": True}},
            )
            assert (
                await collect(call, 6)
                == [
                    Subtitle("learner", "g2", "I like", False),
                    LearnerTurn("g2"),
                    AudioOut(b"\x02\x00"),
                    Subtitle("learner", "g2", " cats.", False),
                    Subtitle("learner", "g2", "I like cats.", True),
                    Subtitle("tutor", "g3", "", True),
                ][:6]
            )
            await vendor.push({"serverContent": {"turnComplete": True}})

    assert vendor.queries == [f"key={KEY}"]
    (setup,) = vendor.of_kind("setup")
    assert setup["model"] == "models/gemini-3.8-live"
    assert setup["systemInstruction"] == {"parts": [{"text": "Be kind."}]}
    assert setup["generationConfig"] == {"responseModalities": ["AUDIO"]}
    assert setup["inputAudioTranscription"] == setup["outputAudioTranscription"] == {}
    assert setup["contextWindowCompression"] == {"slidingWindow": {}}
    assert setup["sessionResumption"] == {}
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["disabled"] is False
    lookup, end = setup["tools"][0]["functionDeclarations"]
    assert lookup["parameters"] == {
        "type": "OBJECT",
        "properties": {"word": {"type": "STRING", "description": "The word."}},
        "required": ["word"],
    }
    assert "parameters" not in end  # Gemini refuses an object with no properties
    # The tutor speaks first on a cue; the learner's audio is 16 kHz PCM.
    (cue,) = vendor.of_kind("clientContent")
    assert cue == {
        "turns": [{"role": "user", "parts": [{"text": START_CUE}]}],
        "turnComplete": True,
    }
    (heard_audio,) = vendor.of_kind("realtimeInput")
    assert heard_audio["audio"]["mimeType"] == "audio/pcm;rate=16000"
    assert base64.b64decode(heard_audio["audio"]["data"]) == b"\x00\x00" * 160


async def test_interruptions_and_wrap_up_instructions() -> None:
    async with fake_gemini() as vendor:
        call = await open_session(target(vendor), instructions="")
        async with call:
            await vendor.push(said("Let me tell you"), {"serverContent": {"interrupted": True}})
            assert await collect(call, 2) == [
                Subtitle("tutor", "g1", "Let me tell you", False),
                SpeechStarted(),
            ]
            # What the server still sends for the reply is dropped; the reply ends cut short.
            await vendor.push(said(" more"), audio(b"\x01\x00"), turn_complete(10, 5))
            assert await collect(call, 1) == [ResponseDone("cancelled", Usage(10, 5, 5, 5))]
            await call.interrupt(500)  # the server stops replies itself: nothing is sent
            await call.respond("Say goodbye now.")
            (goodbye,) = await until_received(vendor, "clientContent")
            assert goodbye["turns"][0]["parts"] == [{"text": "Say goodbye now."}]
    assert [next(iter(m)) for m in vendor.received] == ["setup", "clientContent"]


async def test_tool_calls_cancellations_and_untrusted_messages() -> None:
    async with fake_gemini() as vendor:
        call = await open_session(target(vendor), instructions="", tools=TOOLS)
        async with call:
            ws = vendor.connections[0]
            await ws.send(b"\xff not json")
            await ws.send("[1, 2]")
            await vendor.push(
                {"somethingNew": {}},
                {"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": "%%%"}}]}}},
                heard("What is a cat?"),
                said("Let me check."),
                {
                    "toolCall": {
                        "functionCalls": [
                            {"id": "c1", "name": "lookup_word", "args": {"word": "cat"}},
                            {"id": "c2", "name": "end_session"},
                            {"name": "no_id"},
                        ]
                    }
                },
                {"toolCall": {"functionCalls": [{"id": "c1", "name": "lookup_word"}]}},
                {"toolCallCancellation": {"ids": ["c2"]}},
            )
            assert await collect(call, 6) == [
                Subtitle("learner", "g1", "What is a cat?", False),
                LearnerTurn("g1"),
                Subtitle("tutor", "g2", "Let me check.", False),
                Subtitle("tutor", "g2", "Let me check.", True),
                ResponseDone("completed", None),
                ToolCalls(
                    (
                        ToolCall("c1", "lookup_word", '{"word": "cat"}'),
                        ToolCall("c2", "end_session", "{}"),
                    )
                ),
            ]
            # The cancellation arrives while the tools run.
            await vendor.push(said("A cat is"), turn_complete())
            assert (await collect(call, 1))[0] == Subtitle("tutor", "g3", "A cat is", False)
            await call.send_tool_results([("c1", '{"word": "cat"}'), ("c2", "plain text")])
            (response,) = await until_received(vendor, "toolResponse")
    assert response == {
        "functionResponses": [{"id": "c1", "name": "lookup_word", "response": {"word": "cat"}}]
    }
    # The model goes on by itself: no extra turn is sent.
    assert vendor.of_kind("clientContent") == []


async def test_go_away_resumes_on_a_new_connection() -> None:
    async with fake_gemini() as vendor:
        call = await open_session(target(vendor), instructions="Hi.", tools=TOOLS)
        async with call:
            events: list[RealtimeEvent] = []

            async def read() -> None:
                async for event in call.events():
                    events.append(event)

            reader = asyncio.create_task(read())
            # Mid-reply the session can't be resumed: the adapter waits for a point
            # that can, keeping the old connection meanwhile.
            await vendor.push(
                {"sessionResumptionUpdate": {"newHandle": "h1", "resumable": True}},
                said("One"),
                {"sessionResumptionUpdate": {"resumable": False}},
                {"goAway": {"timeLeft": "5s"}},
                said(" two"),
                turn_complete(),
            )
            await eventually(lambda: any(isinstance(e, ResponseDone) for e in events))
            assert len(vendor.connections) == 1
            await vendor.push({"sessionResumptionUpdate": {"newHandle": "h2", "resumable": True}})
            setups = await until_received(vendor, "setup", 2)
            assert setups[1]["sessionResumption"] == {"handle": "h2"}
            assert setups[1]["tools"] == setups[0]["tools"]
            assert setups[1]["systemInstruction"] == setups[0]["systemInstruction"]
            assert vendor.queries[1] == f"key={KEY}"
            await call.send_audio(b"\x00\x00" * 10)
            (sent,) = await until_received(vendor, "realtimeInput")
            assert sent["audio"]["mimeType"] == "audio/pcm;rate=16000"
            await vendor.push(said("Three"), turn_complete())
            await eventually(lambda: sum(isinstance(e, ResponseDone) for e in events) == 2)
            assert Subtitle("tutor", "g2", "Three", True) in events
            assert vendor.connections[0].close_code is not None  # the old one is gone
            reader.cancel()


async def test_held_messages_go_out_after_resuming() -> None:
    """Sent while the old connection is closing: held, then sent on the new one."""
    async with fake_gemini() as vendor:
        call = await open_session(target(vendor), instructions="")
        async with call:
            reader = asyncio.create_task(collect(call, 99))
            await vendor.push(
                {"sessionResumptionUpdate": {"newHandle": "h1", "resumable": False}},
                {"goAway": {"timeLeft": "0s"}},
            )
            await asyncio.sleep(0.05)
            await vendor.hang_up()
            for _ in range(3):
                await call.send_audio(b"\x00\x00")
            setups = await until_received(vendor, "setup", 2)
            assert setups[1]["sessionResumption"] == {"handle": "h1"}
            assert len(await until_received(vendor, "realtimeInput", 3)) == 3
            reader.cancel()


async def test_a_failed_resumption_ends_the_session() -> None:
    async with fake_gemini() as vendor:
        call = await open_session(target(vendor), instructions="")
        async with call:
            vendor.refuse = True
            await vendor.push(
                {"sessionResumptionUpdate": {"newHandle": "h1", "resumable": False}},
                {"goAway": {"timeLeft": "0s"}},
            )
            await asyncio.sleep(0.05)
            await vendor.connections[0].close(1011, "internal error ?key=leaked")
            events = await collect(call, 99)
    assert events == [VendorError("1011", "internal error ?key=***")]


async def test_connect_failures_are_reported_for_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async with fake_gemini() as vendor:
        vendor.refuse = True
        with pytest.raises(RealtimeConnectError, match="API key not valid") as refused:
            await open_session(target(vendor), instructions="")
        assert KEY not in str(refused.value)
        dead = vendor.url.replace(vendor.url.split(":")[2].split("/")[0], "1")
    with pytest.raises(RealtimeConnectError) as unreachable:
        await open_session(replace(target(vendor), url=f"{dead}?alt=1"), instructions="")
    assert KEY not in str(unreachable.value)
    assert KEY not in json.dumps(unreachable.value.args)

    keyless = target(vendor)
    keyless = replace(keyless, model=replace(keyless.model, api_key=None))
    with pytest.raises(RealtimeConnectError, match="no API key"):
        await open_session(keyless, instructions="")
