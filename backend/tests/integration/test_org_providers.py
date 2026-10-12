"""A member's provider context: the main account's connections where theirs have none
(ADR 0031 §5-6)."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TenantMember
from app.org.quotas import DEFAULT_QUOTAS
from app.providers import net_guard
from app.providers.llm import get_chat_models
from app.providers.net_guard import IPAddress
from app.providers.tenant import load_provider_context
from app.usage.recorder import UsageRecorder

SECRET = "sk-live-abcdefghijklmnop"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    import ipaddress

    async def fake_resolve(host: str, port: int) -> list[IPAddress]:
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(net_guard, "resolve", fake_resolve)


async def _client(app: FastAPI, name: str) -> AsyncClient:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    response = await client.post(
        "/auth/register",
        json={"email": f"{name}@example.com", "password": "password123", "display_name": name},
    )
    assert response.status_code == 201
    return client


async def _tenant(session: AsyncSession, client: AsyncClient) -> uuid.UUID:
    user_id = uuid.UUID((await client.get("/auth/me")).json()["user"]["id"])
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    )
    assert tenant_id is not None
    return tenant_id


def _chat(routes: list[dict[str, Any]]) -> dict[str, Any]:
    return next(r for r in routes if r["section"] == "llm" and r["task"] == "chat")


async def _setup(app: FastAPI) -> tuple[AsyncClient, AsyncClient]:
    owner = await _client(app, "owner")
    created = await owner.post("/tenant/connections", json={"preset": "openai", "api_key": SECRET})
    assert created.status_code == 201
    member = await _client(app, "member")
    code = (await owner.post("/org/invites", json={})).json()["code"]
    assert (await member.post("/org/join", json={"code": code})).status_code == 201
    return owner, member


async def test_member_uses_main_accounts_connection_without_seeing_it(
    app: FastAPI, db_session: AsyncSession
) -> None:
    owner, member = await _setup(app)
    owner_tenant = await _tenant(db_session, owner)
    member_tenant = await _tenant(db_session, member)

    ctx = await load_provider_context(db_session, member_tenant)
    assert ctx.connections == {}
    assert ctx.sponsor is not None and ctx.sponsor.name == "owner"
    assert ctx.sponsor.ctx.tenant_id == owner_tenant

    # Calls are labelled with the main account as payer.
    (model,) = get_chat_models(ctx, "chat")
    recorder = model.callbacks[0]  # type: ignore[index]
    assert isinstance(recorder, UsageRecorder)
    assert recorder.labels.tenant_id == member_tenant
    assert recorder.labels.billed_tenant_id == owner_tenant

    # Settings: the member's own connections stay empty; routes say who provides them.
    assert (await member.get("/tenant/connections")).json() == []
    chat = _chat((await member.get("/tenant/routes")).json())
    assert chat["effective"] == ["openai:gpt-5-mini"]
    assert (chat["provided_by"], chat["quota_exhausted"]) == ("owner", False)
    assert SECRET[-4:] not in (await member.get("/tenant/routes")).text
    # The main account's own view is unchanged.
    assert _chat((await owner.get("/tenant/routes")).json())["provided_by"] is None


async def test_own_connection_wins_and_leaving_ends_it_at_once(
    app: FastAPI, db_session: AsyncSession
) -> None:
    _, member = await _setup(app)
    member_tenant = await _tenant(db_session, member)
    await member.post("/tenant/connections", json={"preset": "openai", "api_key": SECRET})
    chat = _chat((await member.get("/tenant/routes")).json())
    assert (chat["effective"], chat["provided_by"]) == (["openai:gpt-5-mini"], None)
    (model,) = get_chat_models(await load_provider_context(db_session, member_tenant), "chat")
    assert model.callbacks[0].labels.billed_tenant_id is None  # type: ignore[index, union-attr]

    await member.delete(
        "/tenant/connections/" + (await member.get("/tenant/connections")).json()[0]["id"]
    )
    assert _chat((await member.get("/tenant/routes")).json())["provided_by"] == "owner"
    before = await load_provider_context(db_session, member_tenant)
    assert (await member.delete("/org/membership")).status_code == 204
    after = await load_provider_context(db_session, member_tenant)
    assert after.sponsor is None and after.version != before.version
    chat = _chat((await member.get("/tenant/routes")).json())
    assert (chat["effective"], chat["provided_by"]) == ([], None)


async def test_zero_quota_reads_as_used_up(app: FastAPI) -> None:
    owner, member = await _setup(app)
    membership_id = (await owner.get("/org/members")).json()[0]["id"]
    quotas = DEFAULT_QUOTAS.model_dump() | {"text": {"daily": 0, "monthly": None}}
    await owner.put(f"/org/members/{membership_id}/quotas", json=quotas)
    chat = _chat((await member.get("/tenant/routes")).json())
    assert (chat["effective"], chat["provided_by"], chat["quota_exhausted"]) == (
        [],
        "owner",
        True,
    )
