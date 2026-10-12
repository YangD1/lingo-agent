"""Invites, joining, leaving and quotas over the API (ADR 0031 §1-3)."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OrgInvite, OrgMembership, TenantMember, TtsAudio
from app.org.quotas import DEFAULT_QUOTAS


async def _client(app: FastAPI, email: str) -> AsyncClient:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
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


async def _invite(client: AsyncClient, **body: object) -> str:
    response = await client.post("/org/invites", json=body)
    assert response.status_code == 201, response.text
    code: str = response.json()["code"]
    return code


async def test_endpoints_require_login(client: AsyncClient) -> None:
    for method, path in (
        ("GET", "/org/invites"),
        ("GET", "/org/members"),
        ("GET", "/org/membership"),
        ("POST", "/org/join"),
    ):
        assert (await client.request(method, path, json={"code": "x"})).status_code == 401


async def test_invite_preview_join_and_leave(app: FastAPI, db_session: AsyncSession) -> None:
    owner = await _client(app, "owner@example.com")
    member = await _client(app, "member@example.com")
    code = await _invite(owner)

    listed = (await owner.get("/org/invites")).json()
    assert len(listed) == 1 and "code" not in listed[0]
    assert listed[0]["max_uses"] == 1 and listed[0]["used_count"] == 0

    preview = (await member.post("/org/join/preview", json={"code": code})).json()
    assert preview["sponsor_name"] == "owner"
    assert preview["quotas"] == DEFAULT_QUOTAS.model_dump()
    assert (await member.get("/org/membership")).json() is None  # preview doesn't join

    joined = await member.post("/org/join", json={"code": code})
    assert joined.status_code == 201
    assert joined.json()["sponsor_name"] == "owner"
    assert (await member.get("/org/membership")).json()["sponsor_name"] == "owner"

    # Used up: one use by default (Q65i), and it leaves the open list.
    other = await _client(app, "other@example.com")
    assert (await other.post("/org/join", json={"code": code})).json()["detail"][
        "code"
    ] == "invite_invalid"
    assert (await owner.get("/org/invites")).json() == []

    members = (await owner.get("/org/members")).json()
    assert [(m["email"], m["display_name"], m["status"]) for m in members] == [
        ("member@example.com", "member", "active")
    ]
    assert set(members[0]) == {
        "id",
        "display_name",
        "email",
        "status",
        "joined_at",
        "ended_at",
        "quotas",
        "usage",
    }
    assert members[0]["usage"]["text"] == {"day": 0, "month": 0}

    assert (await member.delete("/org/membership")).status_code == 204
    assert (await member.get("/org/membership")).json() is None
    assert (await member.delete("/org/membership")).status_code == 404
    members = (await owner.get("/org/members")).json()
    assert members[0]["status"] == "left" and members[0]["ended_at"] is not None


async def test_join_refuses_own_invite_and_second_main_account(app: FastAPI) -> None:
    a = await _client(app, "a@example.com")
    b = await _client(app, "b@example.com")
    member = await _client(app, "m@example.com")
    own = await _invite(a)
    assert (await a.post("/org/join", json={"code": own})).json()["detail"]["code"] == "own_invite"

    assert (await member.post("/org/join", json={"code": own})).status_code == 201
    other = await _invite(b)
    response = await member.post("/org/join", json={"code": other})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_member"
    # The refused join didn't take a use.
    assert (await b.get("/org/invites")).json()[0]["used_count"] == 0


async def test_unknown_expired_and_revoked_codes_look_the_same(
    app: FastAPI, db_session: AsyncSession
) -> None:
    owner = await _client(app, "owner@example.com")
    member = await _client(app, "member@example.com")
    revoked = await _invite(owner)
    invite_id = (await owner.get("/org/invites")).json()[0]["id"]
    assert (await owner.delete(f"/org/invites/{invite_id}")).status_code == 204
    expired = await _invite(owner)
    row = await db_session.scalar(select(OrgInvite).where(OrgInvite.revoked_at.is_(None)))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    for code in (revoked, expired, "no-such-code"):
        for path in ("/org/join/preview", "/org/join"):
            response = await member.post(path, json={"code": code})
            assert response.status_code == 404
            assert response.json()["detail"]["code"] == "invite_invalid"


async def test_multi_use_invite(app: FastAPI) -> None:
    owner = await _client(app, "owner@example.com")
    code = await _invite(owner, max_uses=None, days=30)
    for i in range(3):
        member = await _client(app, f"m{i}@example.com")
        assert (await member.post("/org/join", json={"code": code})).status_code == 201
    assert (await owner.get("/org/invites")).json()[0]["used_count"] == 3


async def test_quotas_template_and_per_member(app: FastAPI) -> None:
    owner = await _client(app, "owner@example.com")
    template = DEFAULT_QUOTAS.model_dump() | {"tts": {"daily": 0, "monthly": None}}
    assert (await owner.put("/org/default-quotas", json=template)).status_code == 200
    assert (await owner.get("/org/default-quotas")).json() == template
    bad = await owner.put("/org/default-quotas", json={"text": {"daily": -1}})
    assert bad.status_code == 422

    member = await _client(app, "member@example.com")
    await member.post("/org/join", json={"code": await _invite(owner)})
    assert (await member.get("/org/membership")).json()["quotas"] == template

    membership_id = (await owner.get("/org/members")).json()[0]["id"]
    changed = template | {"text": {"daily": 1000, "monthly": None}}
    response = await owner.put(f"/org/members/{membership_id}/quotas", json=changed)
    assert response.status_code == 200 and response.json()["quotas"] == changed
    assert (await member.get("/org/membership")).json()["quotas"] == changed
    # Changing the template later leaves existing members alone.
    await owner.put("/org/default-quotas", json=DEFAULT_QUOTAS.model_dump())
    assert (await member.get("/org/membership")).json()["quotas"] == changed


async def test_main_account_cannot_touch_others_members(app: FastAPI) -> None:
    owner = await _client(app, "owner@example.com")
    stranger = await _client(app, "stranger@example.com")
    member = await _client(app, "member@example.com")
    await member.post("/org/join", json={"code": await _invite(owner)})
    membership_id = (await owner.get("/org/members")).json()[0]["id"]
    invite_id = (await owner.post("/org/invites", json={})).json()["id"]

    assert (await stranger.get("/org/members")).json() == []
    quotas = DEFAULT_QUOTAS.model_dump()
    assert (
        await stranger.put(f"/org/members/{membership_id}/quotas", json=quotas)
    ).status_code == 404
    assert (await stranger.delete(f"/org/members/{membership_id}")).status_code == 404
    assert (await stranger.delete(f"/org/invites/{invite_id}")).status_code == 404


async def test_removing_member_clears_their_unpinned_audio(
    app: FastAPI, db_session: AsyncSession
) -> None:
    owner = await _client(app, "owner@example.com")
    member = await _client(app, "member@example.com")
    await member.post("/org/join", json={"code": await _invite(owner)})
    sponsor_id = await _tenant(db_session, owner)
    member_user = uuid.UUID((await member.get("/auth/me")).json()["user"]["id"])
    owner_user = uuid.UUID((await owner.get("/auth/me")).json()["user"]["id"])

    def audio(key: str, user_id: uuid.UUID | None, pinned: bool = False) -> TtsAudio:
        return TtsAudio(
            tenant_id=sponsor_id,
            user_id=user_id,
            key=key,
            language="en-US",
            connection_name="c",
            model="m",
            voice="v",
            mime_type="audio/mpeg",
            audio=b"x",
            size=1,
            pinned=pinned,
        )

    db_session.add_all(
        [audio("a", member_user), audio("b", member_user, pinned=True), audio("c", owner_user)]
    )
    await db_session.commit()

    membership_id = (await owner.get("/org/members")).json()[0]["id"]
    assert (await owner.delete(f"/org/members/{membership_id}")).status_code == 204
    assert (await member.get("/org/membership")).json() is None
    db_session.expire_all()
    keys = set(await db_session.scalars(select(TtsAudio.key)))
    assert keys == {"b", "c"}
    status = await db_session.scalar(select(OrgMembership.status))
    assert status == "removed"
    # Removed members can join again with a new invite.
    again = await member.post("/org/join", json={"code": await _invite(owner)})
    assert again.status_code == 201
