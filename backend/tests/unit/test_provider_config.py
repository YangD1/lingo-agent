from pathlib import Path
from typing import Any

import pytest
import yaml

from app.providers.config import (
    RouteSpec,
    load_providers_config,
    resolve_route,
    resolve_route_with_source,
)
from app.providers.errors import NoModelConfiguredError, ProviderConfigError
from app.settings import REPO_ROOT
from tests.unit.provider_fixtures import conn, make_config, make_ctx


@pytest.mark.parametrize("name", ["providers.dev.yaml", "providers.prod.yaml"])
def test_shipped_configs_are_valid(name: str) -> None:
    config = load_providers_config(REPO_ROOT / "config" / name)
    assert "chat" in config.llm.routes
    assert all(p.base_url.startswith("http") for p in config.presets.values())


def test_shipped_configs_contain_no_secrets() -> None:
    for path in (REPO_ROOT / "config").glob("providers.*.yaml"):
        text = path.read_text()
        assert "api_key" not in text and "sk-" not in text, path


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ProviderConfigError, match="not found"):
        load_providers_config(tmp_path / "nope.yaml")


def test_invalid_file_raises_provider_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"presets": {}, "llm": {"default": "x:y"}}))
    with pytest.raises(ProviderConfigError, match="unknown preset 'x'"):
        load_providers_config(path)


def test_api_key_env_is_no_longer_accepted() -> None:
    with pytest.raises(ValueError, match="api_key_env"):
        make_config(
            presets={"d": {"kind": "deepseek", "base_url": "https://x", "api_key_env": "K"}},
            llm={"default": "d:m"},
            embedding=None,
        )


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        (None, "http://host:1/v1"),
        ("", "http://host:1/v1"),
        ("http://asr:8000/v1", "http://asr:8000/v1"),
    ],
)
def test_preset_base_url_env_overrides_when_set(
    monkeypatch: pytest.MonkeyPatch, env_value: str | None, expected: str
) -> None:
    if env_value is None:
        monkeypatch.delenv("LOCAL_ASR_URL", raising=False)
    else:
        monkeypatch.setenv("LOCAL_ASR_URL", env_value)
    config = make_config(
        presets={
            "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1"},
            "local": {
                "kind": "openai_compatible",
                "base_url": "http://host:1/v1",
                "base_url_env": "LOCAL_ASR_URL",
            },
        },
        llm={"default": "openai:gpt-5-mini"},
    )
    assert config.presets["local"].base_url == expected


def test_malformed_model_ref_rejected() -> None:
    with pytest.raises(ValueError, match="<connection>:<model>"):
        make_config(llm={"default": "deepseek"})


def test_embedding_fallback_chain_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one model"):
        make_config(embedding={"default": ["openai:a", "openai:b"]})


def test_embedding_on_kind_without_embeddings_rejected() -> None:
    with pytest.raises(ValueError, match="does not support embeddings"):
        make_config(embedding={"default": "anthropic:some-model"})


def test_route_shorthands_normalize() -> None:
    config = make_config()
    assert config.llm.default.models == ["deepseek:deepseek-chat", "openai:gpt-5-mini"]
    assert config.llm.routes["chat"].params == {"temperature": 0.7}


# --- per-tenant resolution ------------------------------------------------------------


def test_default_route_uses_connections_named_after_presets() -> None:
    ctx = make_ctx(conn("deepseek"), conn("openai"))
    models = resolve_route(make_config(), ctx, "llm", "unknown-task")
    assert [(m.connection, m.model) for m in models] == [
        ("deepseek", "deepseek-chat"),
        ("openai", "gpt-5-mini"),
    ]


def test_models_without_tenant_connection_are_skipped() -> None:
    models = resolve_route(make_config(), make_ctx(conn("openai")), "llm", "default")
    assert [m.connection for m in models] == ["openai"]


def test_no_connection_at_all_raises_with_code() -> None:
    with pytest.raises(NoModelConfiguredError) as info:
        resolve_route(make_config(), make_ctx(), "llm", "chat")
    assert info.value.code == "no_llm_configured"


def test_tenant_route_override_wins() -> None:
    ctx = make_ctx(
        conn("relay", "anthropic", base_url="https://relay.example.com"),
        routes={
            ("llm", "chat"): RouteSpec(
                models=["relay:claude-sonnet-5"], params={"temperature": 0.2}
            )
        },
    )
    (model,) = resolve_route(make_config(), ctx, "llm", "chat")
    assert (model.connection, model.kind, model.model) == ("relay", "anthropic", "claude-sonnet-5")
    assert model.base_url == "https://relay.example.com"
    assert model.params["temperature"] == 0.2


def test_params_layering_defaults_then_connection_then_route() -> None:
    ctx = make_ctx(conn("openai", timeout=60, max_retries=3))
    (model,) = resolve_route(make_config(), ctx, "llm", "chat")
    assert model.params == {"timeout": 60, "max_retries": 3, "temperature": 0.7}


def test_task_params_sit_between_defaults_and_the_connection() -> None:
    config = make_config(
        llm={
            "default": ["deepseek:deepseek-chat", "openai:gpt-5-mini"],
            "routes": {"chat": {"models": ["openai:gpt-5-mini"], "timeout": 45}},
            "task_params": {"slow": {"timeout": 120}, "chat": {"timeout": 90}},
        }
    )
    # On the default route, and on a task without a route of its own.
    (model,) = resolve_route(config, make_ctx(conn("openai")), "llm", "slow")
    assert model.params == {"timeout": 120, "max_retries": 1}
    # Each model of the auto fallback (no route matches a connection) gets them too.
    auto = make_ctx(conn("relay", "openai_compatible", default_model="m"))
    (model,) = resolve_route(config, auto, "llm", "slow")
    assert model.params["timeout"] == 120
    # The connection's own params and the route's win.
    (model,) = resolve_route(config, make_ctx(conn("openai", timeout=200)), "llm", "slow")
    assert model.params["timeout"] == 200
    (model,) = resolve_route(config, make_ctx(conn("openai")), "llm", "chat")
    assert model.params["timeout"] == 45
    # Other tasks keep the defaults.
    (model,) = resolve_route(config, make_ctx(conn("openai")), "llm", "other")
    assert model.params["timeout"] == 30


def test_shipped_configs_give_slow_tasks_a_longer_timeout() -> None:
    for name in ("providers.dev.yaml", "providers.prod.yaml"):
        config = load_providers_config(REPO_ROOT / "config" / name)
        timeouts = {t: p["timeout"] for t, p in config.llm.task_params.items()}
        for task in ("exercise_generate", "exercise_critic", "reading_critic", "writing_review"):
            assert timeouts[task] > config.defaults["timeout"], (name, task)


def test_keyless_connection_is_usable() -> None:
    ctx = make_ctx(conn("openai", key=None))
    (model,) = resolve_route(make_config(), ctx, "llm", "chat")
    assert model.api_key is None


def test_api_key_is_secret_in_repr() -> None:
    ctx = make_ctx(conn("openai", key="sk-very-secret"))
    (model,) = resolve_route(make_config(), ctx, "llm", "chat")
    assert "sk-very-secret" not in repr(model)
    assert "sk-very-secret" not in repr(ctx)


# --- ADR 0007 §3: default models as the last resort ---------------------------------------


def refs(chain: list[Any]) -> list[str]:
    return [f"{m.connection}:{m.model}" for m in chain]


def test_auto_fallback_uses_default_models_in_creation_order() -> None:
    ctx = make_ctx(
        conn("relay-b", "openai_compatible", default_model="model-b"),
        conn("no-default", "openai_compatible"),
        conn("relay-a", "openai_compatible", default_model="model-a"),
    )
    chain, source = resolve_route_with_source(make_config(), ctx, "llm", "chat")
    assert source == "auto"
    assert refs(chain) == ["relay-b:model-b", "relay-a:model-a"]  # insertion = creation order
    assert chain[0].params["temperature"] == 0.7  # the task's route params still apply


def test_auto_fallback_skips_speech_to_text_default_models() -> None:
    ctx = make_ctx(
        conn("siliconflow", "openai_compatible", default_model="FunAudioLLM/SenseVoiceSmall"),
        conn("local", "openai_compatible", default_model="Systran/faster-whisper-small"),
        conn("relay", "openai_compatible", default_model="relay-model"),
    )
    chain, _ = resolve_route_with_source(make_config(), ctx, "llm", "chat")
    assert refs(chain) == ["relay:relay-model"]


def test_matching_yaml_route_is_not_extended_by_default_models() -> None:
    ctx = make_ctx(
        conn("relay", "openai_compatible", default_model="relay-model"),
        conn("openai", default_model="gpt-5-nano"),
    )
    chain, source = resolve_route_with_source(make_config(), ctx, "llm", "chat")
    assert source == "default"
    assert refs(chain) == ["openai:gpt-5-mini"]  # the YAML route, as written


def test_override_is_reported_as_such() -> None:
    ctx = make_ctx(
        conn("relay", "openai_compatible", default_model="relay-model"),
        routes={("llm", "chat"): RouteSpec(models=["relay:other-model"])},
    )
    chain, source = resolve_route_with_source(make_config(), ctx, "llm", "chat")
    assert (refs(chain), source) == (["relay:other-model"], "override")


def test_override_matching_nothing_falls_back_to_default_models() -> None:
    ctx = make_ctx(
        conn("relay", "openai_compatible", default_model="relay-model"),
        routes={("llm", "chat"): RouteSpec(models=["deleted:some-model"])},
    )
    chain, source = resolve_route_with_source(make_config(), ctx, "llm", "chat")
    assert (refs(chain), source) == (["relay:relay-model"], "auto")


def test_embeddings_never_fall_back_to_chat_models() -> None:
    ctx = make_ctx(conn("relay", "openai_compatible", default_model="relay-model"))
    with pytest.raises(NoModelConfiguredError):
        resolve_route(make_config(), ctx, "embedding", "default")


def test_no_default_models_still_means_not_configured() -> None:
    ctx = make_ctx(conn("relay", "openai_compatible"))
    with pytest.raises(NoModelConfiguredError):
        resolve_route(make_config(), ctx, "llm", "chat")


# --- switched-off models (ADR 0026) ------------------------------------------------------


def test_disabled_models_are_skipped_and_the_rest_keep_their_order() -> None:
    ctx = make_ctx(
        conn("relay", "openai_compatible"),
        conn("openai"),
        routes={
            ("llm", "chat"): RouteSpec(
                models=["relay:a", "openai:b", "relay:c"], disabled=["openai:b"]
            )
        },
    )
    chain, source = resolve_route_with_source(make_config(), ctx, "llm", "chat")
    assert (refs(chain), source) == (["relay:a", "relay:c"], "override")


def test_all_disabled_never_falls_back_to_default_models() -> None:
    ctx = make_ctx(
        conn("relay", "openai_compatible", default_model="relay-model"),
        routes={("llm", "chat"): RouteSpec(models=["relay:a"], disabled=["relay:a"])},
    )
    with pytest.raises(NoModelConfiguredError) as info:
        resolve_route(make_config(), ctx, "llm", "chat")
    assert info.value.code == "models_disabled"


def test_disabled_rows_left_with_only_missing_connections_do_not_fall_back() -> None:
    # The usable row is switched off and the other one's connection is gone: still strict.
    ctx = make_ctx(
        conn("relay", "openai_compatible", default_model="relay-model"),
        routes={("llm", "chat"): RouteSpec(models=["relay:a", "deleted:b"], disabled=["relay:a"])},
    )
    with pytest.raises(NoModelConfiguredError) as info:
        resolve_route(make_config(), ctx, "llm", "chat")
    assert info.value.code == "models_disabled"


def test_disabled_vision_and_speech_routes_use_the_disabled_code() -> None:
    ctx = make_ctx(
        conn("openai"),
        routes={("llm", "vision"): RouteSpec(models=["openai:v"], disabled=["openai:v"])},
    )
    with pytest.raises(NoModelConfiguredError) as info:
        resolve_route(make_config(), ctx, "llm", "vision")
    assert info.value.code == "models_disabled"


def test_disabled_must_be_part_of_the_route() -> None:
    with pytest.raises(ValueError, match="not in the route"):
        RouteSpec(models=["openai:a"], disabled=["openai:b"])


def test_disabled_is_not_mistaken_for_a_call_param() -> None:
    route = RouteSpec.model_validate({"models": ["openai:a"], "disabled": ["openai:a"]})
    assert (route.params, route.disabled) == ({}, ["openai:a"])
