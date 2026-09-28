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
