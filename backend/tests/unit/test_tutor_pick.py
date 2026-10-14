"""The learner's tutor picks change only the chains they are for (ADR 0032 §1, §3)."""

import uuid
from dataclasses import replace
from typing import Any

import pytest

from app.agents.chat_graph import system_prompt
from app.providers import realtime, tts
from app.providers.config import RouteSpec, Sponsor, TutorPick, resolve_route
from tests.unit.provider_fixtures import conn, make_config, make_ctx

MAIN = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
PRESETS = {
    "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1"},
    "deepseek": {"kind": "deepseek", "base_url": "https://api.deepseek.com/v1"},
    "qwen": {"kind": "openai_compatible", "base_url": "https://dashscope.aliyuncs.com/v1"},
}


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> Any:
    config = make_config(
        presets=PRESETS,
        llm={
            "default": ["deepseek:deepseek-chat", "openai:gpt-5-mini"],
            "routes": {"chat": ["deepseek:deepseek-chat", "openai:gpt-5-mini"]},
        },
        tts={"default": ["openai:gpt-4o-mini-tts", "qwen:qwen3-tts-flash"]},
        realtime={"default": ["openai:gpt-realtime-2.1", "qwen:qwen3.5-omni-flash-realtime"]},
    )
    monkeypatch.setattr(tts, "get_providers_config", lambda: config)
    monkeypatch.setattr(realtime, "get_providers_config", lambda: config)
    return config


def _ctx(tutor: TutorPick | None = None) -> Any:
    ctx = make_ctx(
        conn("deepseek"),
        conn("openai", base_url="https://api.openai.com/v1"),
        conn("qwen", "openai_compatible", base_url="https://dashscope.aliyuncs.com/v1"),
    )
    return replace(ctx, tutor=tutor)


def _refs(models: Any) -> list[str]:
    return [f"{m.connection}:{m.model}" for m in models]


def test_the_picked_chat_model_goes_first_the_rest_stay_fallbacks(config: Any) -> None:
    ctx = _ctx(TutorPick(chat_model="openai:gpt-5-mini"))
    assert _refs(resolve_route(config, ctx, "llm", "chat")) == [
        "openai:gpt-5-mini",
        "deepseek:deepseek-chat",
    ]
    # Other tasks keep the settings page's order, even on the same models.
    assert _refs(resolve_route(config, ctx, "llm", "default"))[0] == "deepseek:deepseek-chat"


def test_a_pick_no_longer_in_the_chain_changes_nothing(config: Any) -> None:
    ctx = _ctx(TutorPick(chat_model="gone:model"))
    assert _refs(resolve_route(config, ctx, "llm", "chat"))[0] == "deepseek:deepseek-chat"


def test_a_member_picks_in_the_main_accounts_chain(config: Any) -> None:
    lent = replace(make_ctx(conn("deepseek"), conn("openai"), version="main"), tenant_id=MAIN)
    ctx = replace(
        make_ctx(),
        sponsor=Sponsor(ctx=lent, name="Main"),
        tutor=TutorPick(chat_model="openai:gpt-5-mini"),
    )
    first, second = resolve_route(config, ctx, "llm", "chat")
    assert (first.model, first.billed_tenant_id) == ("gpt-5-mini", MAIN)
    assert second.billed_tenant_id == MAIN


def test_switched_off_models_stay_off_even_when_picked(config: Any) -> None:
    routes = {
        ("llm", "chat"): RouteSpec(
            models=["deepseek:deepseek-chat", "openai:gpt-5-mini"], disabled=["openai:gpt-5-mini"]
        )
    }
    ctx = replace(make_ctx(conn("deepseek"), conn("openai"), routes=routes))
    ctx = replace(ctx, tutor=TutorPick(chat_model="openai:gpt-5-mini"))
    assert _refs(resolve_route(config, ctx, "llm", "chat")) == ["deepseek:deepseek-chat"]


def test_read_aloud_voices_apply_to_their_model_only(config: Any) -> None:
    pick = TutorPick(tts_model="openai:gpt-4o-mini-tts", voices={"en-US": "sage"})
    speaker = tts.get_tts(_ctx(pick))
    first, fallback = speaker.models
    assert speaker.voice_for(first, "en-US") == "sage"
    assert speaker.voice_for(first, "zh-CN") == tts.default_voice(first, "zh-CN")
    assert speaker.voice_for(fallback, "en-US") == "Jennifer"  # the route's own
    # Picked for another model: not applied.
    other = TutorPick(tts_model="qwen:qwen3-tts-flash", voices={"en-US": "Ethan"})
    assert tts.get_tts(_ctx(other)).voice_for(first, "en-US") == "coral"


def test_word_audio_keeps_its_routes_voices(config: Any) -> None:
    pick = TutorPick(tts_model="openai:gpt-4o-mini-tts", voices={"en-US": "sage"})
    # No usable words route: words read like `default`, but with the route's voices.
    words = tts.get_tts(_ctx(pick), tts.WORDS_TASK)
    assert words.voice_for(words.models[0], "en-US") == "coral"


def test_call_voice_and_model(config: Any) -> None:
    pick = TutorPick(realtime_model="qwen:qwen3.5-omni-flash-realtime", realtime_voice="Aiden")
    first, fallback = realtime.get_realtime(_ctx(pick)).targets
    assert (first.model.model, first.voice) == ("qwen3.5-omni-flash-realtime", "Aiden")
    assert fallback.voice == "marin"  # OpenAI's, as before
    (default,) = realtime.get_realtime(_ctx()).targets[:1]
    assert default.voice == "marin"


def test_the_name_goes_into_the_prompt() -> None:
    assert "Your name is Max" in system_prompt("", name="Max")
    assert "Your name is JOJO" in system_prompt("")
