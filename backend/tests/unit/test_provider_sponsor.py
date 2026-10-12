"""A member's tasks use the main account's connections only where their own have none
(ADR 0031 §5-6)."""

import uuid
from dataclasses import replace

import pytest

from app.providers.config import (
    ConnectionSpec,
    RouteSpec,
    Sponsor,
    TenantProviderContext,
    context_for,
    own_only,
    resolve_route,
    resolve_route_with_source,
)
from app.providers.errors import NoModelConfiguredError, QuotaExhaustedError
from tests.unit.provider_fixtures import conn, make_config, make_ctx

MAIN = uuid.UUID("00000000-0000-0000-0000-0000000000bb")


def _member(
    *own: ConnectionSpec,
    exhausted: frozenset[str] = frozenset(),
    routes: dict[tuple[str, str], RouteSpec] | None = None,
) -> TenantProviderContext:
    lent = replace(make_ctx(conn("openai"), version="main"), tenant_id=MAIN)
    member = make_ctx(*own, routes=routes)
    return replace(member, sponsor=Sponsor(ctx=lent, name="Main", exhausted=exhausted))


def test_member_without_own_model_uses_main_accounts_and_is_billed_to_it() -> None:
    (model,) = resolve_route(make_config(), _member(), "llm", "chat")
    assert (model.connection, model.model) == ("openai", "gpt-5-mini")
    assert model.billed_tenant_id == MAIN
    assert model.api_key is not None  # decrypted server-side only


def test_member_with_own_model_never_mixes_in_main_accounts() -> None:
    models = resolve_route(make_config(), _member(conn("deepseek")), "llm", "default")
    assert [(m.connection, m.billed_tenant_id) for m in models] == [("deepseek", None)]


def test_decided_per_task() -> None:
    # The member's deepseek can't serve the chat route (openai only): the main account's
    # does; the default route lists deepseek, so it stays the member's own.
    config = make_config()
    ctx = _member(conn("deepseek", default_model=None))
    (chat,) = resolve_route(config, ctx, "llm", "chat")
    assert chat.billed_tenant_id == MAIN
    assert resolve_route(config, ctx, "llm", "default")[0].billed_tenant_id is None


def test_models_the_member_switched_off_stay_off() -> None:
    routes = {
        ("llm", "chat"): RouteSpec(models=["openai:gpt-5-mini"], disabled=["openai:gpt-5-mini"])
    }
    ctx = _member(conn("openai"), routes=routes)
    with pytest.raises(NoModelConfiguredError) as raised:
        resolve_route(make_config(), ctx, "llm", "chat")
    assert raised.value.code == "models_disabled"


def test_used_up_quota_reads_as_no_model_with_its_own_code() -> None:
    ctx = _member(exhausted=frozenset({"llm"}))
    with pytest.raises(QuotaExhaustedError) as raised:
        resolve_route(make_config(), ctx, "llm", "chat")
    assert raised.value.code == "quota_exhausted"
    # Another section's quota is untouched.
    (emb,) = resolve_route(make_config(), ctx, "embedding", "default")
    assert emb.billed_tenant_id == MAIN


def test_main_account_without_the_model_is_plain_no_model() -> None:
    lent = replace(make_ctx(conn("deepseek"), version="main"), tenant_id=MAIN)
    ctx = replace(
        make_ctx(),
        sponsor=Sponsor(ctx=lent, name="Main", exhausted=frozenset({"embedding"})),
    )
    with pytest.raises(NoModelConfiguredError) as raised:
        resolve_route(make_config(), ctx, "embedding", "default")
    assert raised.value.code == "no_embedding_configured"


def test_source_and_context_follow_the_main_account() -> None:
    config = make_config()
    ctx = _member()
    _, source = resolve_route_with_source(config, ctx, "llm", "chat")
    assert source == "default"
    assert ctx.sponsor is not None
    assert context_for(config, ctx, "llm", "chat") is ctx.sponsor.ctx
    own = _member(conn("openai"))
    assert context_for(config, own, "llm", "chat") is own


def test_own_only_drops_the_main_account() -> None:
    with pytest.raises(NoModelConfiguredError):
        resolve_route(make_config(), own_only(_member()), "llm", "chat")
    plain = make_ctx()
    assert own_only(plain) is plain
