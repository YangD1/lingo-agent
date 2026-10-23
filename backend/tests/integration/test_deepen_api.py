"""The tenant's limits on the tutor's follow-up segments (ADR 0064 §5)."""

import uuid

from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deepen
from app.db.models import Tenant
from app.deps import require_tenant_manager

DEFAULTS = {
    "enabled": True,
    "max_segments": 1,
    "first_chunk_seconds": 15,
    "total_seconds": 60,
    "max_tokens": 1500,
}


async def login(client: AsyncClient) -> None:
    email = f"{uuid.uuid4()}@example.com"
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201


async def test_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/tenant/deepen")).status_code == 401


def test_only_managers_may_read_or_change() -> None:
    # Members act in their own personal tenant (ADR 0031), so the 403 isn't reachable
    # over HTTP; the dependency itself is covered in test_usage.
    routes = [r for r in deepen.router.routes if isinstance(r, APIRoute)]
    assert {m for r in routes for m in r.methods} == {"GET", "PUT"}
    for route in routes:
        assert require_tenant_manager in {d.call for d in route.dependant.dependencies}


async def test_defaults_then_saved(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    assert (await client.get("/tenant/deepen")).json() == DEFAULTS

    changed = {**DEFAULTS, "enabled": False, "max_segments": 3, "total_seconds": 300}
    put = await client.put("/tenant/deepen", json=changed)
    assert put.status_code == 200
    assert put.json() == changed
    assert (await client.get("/tenant/deepen")).json() == changed
    tenant = await db_session.scalar(select(Tenant))
    assert tenant is not None and tenant.deepen_settings == changed


async def test_out_of_bounds_values_are_refused(client: AsyncClient) -> None:
    await login(client)
    for field, value in (
        ("max_segments", 0),
        ("max_segments", 4),
        ("first_chunk_seconds", 4),
        ("first_chunk_seconds", 61),
        ("total_seconds", 9),
        ("total_seconds", 301),
        ("max_tokens", 255),
        ("max_tokens", 8001),
    ):
        response = await client.put("/tenant/deepen", json={**DEFAULTS, field: value})
        assert response.status_code == 422, (field, value)
    unknown = await client.put("/tenant/deepen", json={**DEFAULTS, "per_day": 10})
    assert unknown.status_code == 422
    assert (await client.get("/tenant/deepen")).json() == DEFAULTS


async def test_each_tenant_has_its_own(app: FastAPI) -> None:
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as one,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as two,
    ):
        await login(one)
        await login(two)
        await one.put("/tenant/deepen", json={**DEFAULTS, "max_tokens": 4000})
        assert (await two.get("/tenant/deepen")).json() == DEFAULTS
