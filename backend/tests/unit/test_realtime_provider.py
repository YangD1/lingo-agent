"""Realtime routes and where each vendor listens (ADR 0030 §2, Q60c)."""

import ipaddress
from typing import Any

import pytest

from app.providers import realtime
from app.providers.config import ResolvedModel, RouteSpec, sdk_params
from app.providers.errors import NoModelConfiguredError, ProviderConfigError
from app.providers.net_guard import validate_realtime_url
from tests.unit.provider_fixtures import conn, make_config, make_ctx

PRESETS: dict[str, Any] = {
    "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1"},
    "qwen": {
        "kind": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "stepfun": {"kind": "openai_compatible", "base_url": "https://api.stepfun.com/v1"},
    "deepseek": {"kind": "deepseek", "base_url": "https://api.deepseek.com/v1"},
}


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> Any:
    config = make_config(
        presets=PRESETS,
        realtime={
            "default": [
                "openai:gpt-realtime-2.1",
                "qwen:qwen3.5-omni-flash-realtime",
                "stepfun:stepaudio-2.5-realtime",
            ]
        },
    )
    monkeypatch.setattr(realtime, "get_providers_config", lambda: config)
    return config


def test_each_vendor_is_reached_in_its_own_spelling(config: Any) -> None:
    ctx = make_ctx(
        conn("openai", base_url="https://api.openai.com/v1"),
        conn(
            "qwen",
            "openai_compatible",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        conn("stepfun", "openai_compatible", base_url="https://api.stepfun.com/v1"),
    )
    targets = realtime.get_realtime(ctx).targets
    assert [(t.url, t.dialect, t.input_rate, t.output_rate) for t in targets] == [
        ("wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1", "ga", 24_000, 24_000),
        (
            "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3.5-omni-flash-realtime",
            "beta",
            16_000,
            24_000,
        ),
        ("wss://api.stepfun.com/v1/realtime?model=stepaudio-2.5-realtime", "beta", 24_000, 24_000),
    ]
    # Connection params still reach the relay: timeouts, retries.
    assert targets[0].model.params["timeout"] == 30


def test_routes_skip_connections_the_tenant_lacks(config: Any) -> None:
    ctx = make_ctx(conn("stepfun", "openai_compatible", base_url="https://api.stepfun.com/v1"))
    (target,) = realtime.get_realtime(ctx).targets
    assert target.model.connection == "stepfun"
    with pytest.raises(NoModelConfiguredError) as caught:
        realtime.get_realtime(make_ctx(conn("deepseek")))
    assert caught.value.code == "no_realtime_model"


def test_qwen_workspace_host_from_the_connection(config: Any) -> None:
    workspace = "wss://ws-1a2b.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
    ctx = make_ctx(
        conn(
            "qwen",
            "openai_compatible",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            realtime_url=workspace,
        ),
        routes={("realtime", "default"): RouteSpec(models=["qwen:qwen3.8-omni-flash-realtime"])},
    )
    (target,) = realtime.get_realtime(ctx).targets
    assert target.url == f"{workspace}?model=qwen3.8-omni-flash-realtime"
    # The workspace host is still Qwen: 16 kHz in, the older spelling.
    assert (target.dialect, target.input_rate) == ("beta", 16_000)


def test_unknown_servers_and_explicit_dialect() -> None:
    relay = conn("relay", "openai_compatible", base_url="https://relay.example.com/openai/v1")
    target = realtime.realtime_target(_resolved(relay, "some-realtime"))
    assert target.url == "wss://relay.example.com/openai/v1/realtime?model=some-realtime"
    assert (target.dialect, target.input_rate) == ("beta", 24_000)

    proxy = conn("proxy", "openai", base_url="https://proxy.example.com/v1")
    assert realtime.realtime_target(_resolved(proxy, "gpt-realtime-2.1")).dialect == "ga"

    told = conn(
        "told", "openai_compatible", base_url="https://relay.example.com/v1", realtime_dialect="ga"
    )
    assert realtime.realtime_target(_resolved(told, "m")).dialect == "ga"
    # Model names are quoted into the query.
    assert realtime.realtime_target(_resolved(relay, "a b&c")).url.endswith("?model=a%20b%26c")


def test_realtime_routes_take_openai_protocol_connections_only() -> None:
    with pytest.raises(ValueError, match="no realtime voice API"):
        make_config(presets=PRESETS, realtime={"default": "deepseek:deepseek-chat"})


def test_realtime_params_never_reach_an_sdk() -> None:
    params = {"timeout": 20, "realtime_url": "wss://x.example.com", "realtime_dialect": "ga"}
    assert sdk_params(params) == {"timeout": 20}


async def test_realtime_url_checked_like_a_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    async def public(host: str, port: int) -> list[Any]:
        return [ipaddress.ip_address("8.8.8.8")]

    monkeypatch.setattr("app.providers.net_guard.resolve", public)
    url = "wss://ws-1.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime/"
    assert await validate_realtime_url(url, allow_private=False) == url.rstrip("/")
    for bad in (
        "https://api.openai.com/v1/realtime",
        "ws://api.openai.com/v1/realtime",
        "wss://user:pw@api.openai.com/v1/realtime",
        "wss://api.openai.com/v1/realtime?model=x",
        "api.openai.com/v1/realtime",
    ):
        with pytest.raises(ProviderConfigError):
            await validate_realtime_url(bad, allow_private=False)
    assert (
        await validate_realtime_url("ws://localhost:9000/v1/realtime", allow_private=True)
        == "ws://localhost:9000/v1/realtime"
    )


def _resolved(spec: Any, model: str) -> ResolvedModel:
    return ResolvedModel(
        connection=spec.name,
        kind=spec.kind,
        model=model,
        base_url=spec.base_url,
        api_key=spec.api_key,
        params=dict(spec.params),
    )
