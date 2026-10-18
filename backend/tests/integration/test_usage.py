import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models import (
    Conversation,
    LLMUsage,
    OrgMembership,
    SpeakingSession,
    Tenant,
    TenantMember,
    User,
)
from app.db.session import create_sessionmaker
from app.deps import require_tenant_manager
from app.org.quotas import Limit, Quotas
from app.providers.latency import LatencyKey, LatencyStats, StallRule, seed_latency_stats
from app.usage.recorder import UsageRecord
from app.usage.writer import UsageWriter


async def make_tenant(session: AsyncSession) -> uuid.UUID:
    tenant = Tenant(name="t", kind="org")
    session.add(tenant)
    await session.commit()
    return tenant.id


def record(tenant_id: uuid.UUID, **overrides: object) -> UsageRecord:
    fields: dict[str, object] = {
        "tenant_id": tenant_id,
        "user_id": None,
        "conversation_id": None,
        "task": "chat",
        "connection_name": "openai",
        "model": "gpt-5-mini",
        "input_tokens": 10,
        "output_tokens": 5,
        "latency_ms": 100,
        "status": "ok",
        "is_fallback": False,
        "error_code": None,
    }
    fields.update(overrides)
    return UsageRecord(**fields)  # type: ignore[arg-type]


async def usage_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(LLMUsage)) or 0


# --- writer -------------------------------------------------------------------------------


async def test_writer_flushes_a_full_batch(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await make_tenant(db_session)
    writer = UsageWriter(create_sessionmaker(db_engine), batch_size=3, flush_interval=60)
    writer.start()
    try:
        for _ in range(3):
            writer.submit(record(tenant_id))
        for _ in range(100):  # the batch is full, so no need to wait for the interval
            if await usage_count(db_session) == 3:
                break
            await asyncio.sleep(0.02)
        assert await usage_count(db_session) == 3
    finally:
        await writer.stop()


async def test_writer_flushes_after_the_interval(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await make_tenant(db_session)
    writer = UsageWriter(create_sessionmaker(db_engine), batch_size=50, flush_interval=0.05)
    writer.start()
    try:
        writer.submit(record(tenant_id))
        await asyncio.sleep(0.3)
        assert await usage_count(db_session) == 1
    finally:
        await writer.stop()


async def test_stop_drains_the_queue(db_engine: AsyncEngine, db_session: AsyncSession) -> None:
    tenant_id = await make_tenant(db_session)
    writer = UsageWriter(create_sessionmaker(db_engine), batch_size=50, flush_interval=60)
    writer.start()
    for _ in range(5):
        writer.submit(record(tenant_id))
    await writer.stop()

    assert await usage_count(db_session) == 5


async def test_writer_stores_prompt_versions_and_cache_reads(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await make_tenant(db_session)
    writer = UsageWriter(create_sessionmaker(db_engine), batch_size=50, flush_interval=60)
    writer.start()
    writer.submit(record(tenant_id, prompts={"route": "0a1b2c3d"}, cached_input_tokens=640))
    writer.submit(record(tenant_id))
    await writer.stop()

    stored = (
        await db_session.execute(
            select(LLMUsage.prompts, LLMUsage.cached_input_tokens).order_by(LLMUsage.id)
        )
    ).all()
    assert [tuple(row) for row in stored] == [({"route": "0a1b2c3d"}, 640), (None, None)]


async def test_full_queue_drops_instead_of_blocking(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await make_tenant(db_session)
    writer = UsageWriter(create_sessionmaker(db_engine), max_queue=2)  # not started
    for _ in range(5):
        writer.submit(record(tenant_id))
    await writer.flush()

    assert writer.dropped == 3
    assert await usage_count(db_session) == 2


async def test_write_failure_keeps_the_writer_alive(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await make_tenant(db_session)
    writer = UsageWriter(create_sessionmaker(db_engine), batch_size=1, flush_interval=60)
    writer.start()
    try:
        writer.submit(record(uuid.uuid4()))  # FK violation: tenant does not exist
        writer.submit(record(tenant_id))
        await asyncio.sleep(0.3)
    finally:
        await writer.stop()

    assert await usage_count(db_session) == 1


# --- /tenant/usage ------------------------------------------------------------------------


async def register(client: AsyncClient, email: str) -> None:
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201


async def tenant_of(session: AsyncSession, email: str) -> uuid.UUID:
    tenant_id = await session.scalar(
        select(TenantMember.tenant_id).join(User).where(User.email == email)
    )
    assert tenant_id is not None
    return tenant_id


async def add_usage(session: AsyncSession, *records: UsageRecord, at: datetime) -> None:
    session.add_all(LLMUsage(**r.__dict__, created_at=at) for r in records)
    await session.commit()


async def test_usage_summary_per_day_and_model(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "owner@example.com")
    tenant_id = await tenant_of(db_session, "owner@example.com")
    now = datetime.now(UTC)
    await add_usage(
        db_session,
        record(tenant_id, input_tokens=10, output_tokens=5, latency_ms=100),
        record(tenant_id, input_tokens=20, output_tokens=7, latency_ms=300, is_fallback=True),
        record(
            tenant_id,
            status="error",
            error_code="APITimeoutError",
            input_tokens=0,
            output_tokens=0,
            latency_ms=200,
        ),
        record(tenant_id, connection_name="deepseek", model="deepseek-chat"),
        at=now,
    )
    await add_usage(db_session, record(tenant_id), at=now - timedelta(days=1))
    await add_usage(db_session, record(tenant_id), at=now - timedelta(days=40))  # out of range

    response = await client.get("/tenant/usage", params={"days": 30})

    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 30
    today, yesterday = now.date().isoformat(), (now - timedelta(days=1)).date().isoformat()
    assert body["rows"] == [
        {
            "day": today,
            "connection": "deepseek",
            "model": "deepseek-chat",
            "calls": 1,
            "input_tokens": 10,
            "output_tokens": 5,
            "characters": 0,
            "errors": 0,
            "fallbacks": 0,
            "avg_latency_ms": 100,
            "member": None,
            "retries": 0,
            "stalls": 0,
            "cancels": 0,
        },
        {
            "day": today,
            "connection": "openai",
            "model": "gpt-5-mini",
            "calls": 3,
            "input_tokens": 30,
            "output_tokens": 12,
            "characters": 0,
            "errors": 1,
            "fallbacks": 1,
            "avg_latency_ms": 200,
            "member": None,
            "retries": 0,
            "stalls": 0,
            "cancels": 0,
        },
        {
            "day": yesterday,
            "connection": "openai",
            "model": "gpt-5-mini",
            "calls": 1,
            "input_tokens": 10,
            "output_tokens": 5,
            "characters": 0,
            "errors": 0,
            "fallbacks": 0,
            "avg_latency_ms": 100,
            "member": None,
            "retries": 0,
            "stalls": 0,
            "cancels": 0,
        },
    ]


async def test_stalls_and_cancels_are_not_errors(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A stalled call retried, then one the learner stopped: no error in either view, but
    both counted apart, since the vendor may bill them (ADR 0014)."""
    await register(client, "owner@example.com")
    tenant_id = await tenant_of(db_session, "owner@example.com")
    await add_usage(
        db_session,
        record(tenant_id, status="stalled", output_tokens=0),
        record(tenant_id, attempt=2),
        record(tenant_id, status="error", attempt=3),
        record(tenant_id, status="cancelled"),
        at=datetime.now(UTC),
    )

    rows = (await client.get("/tenant/usage")).json()["rows"]
    total = (await client.get("/tenant/usage/dashboard")).json()["total"]

    counts = ("calls", "errors", "retries", "stalls", "cancels")
    assert [tuple(r[k] for k in counts) for r in rows] == [(4, 1, 2, 1, 1)]
    assert tuple(total[k] for k in counts) == (4, 1, 2, 1, 1)


async def test_usage_is_tenant_scoped(client: AsyncClient, db_session: AsyncSession) -> None:
    await register(client, "other@example.com")
    other = await tenant_of(db_session, "other@example.com")
    await add_usage(db_session, record(other), at=datetime.now(UTC))
    await register(client, "owner@example.com")  # the client is now logged in as owner

    response = await client.get("/tenant/usage")

    assert response.status_code == 200
    assert response.json()["rows"] == []


async def test_usage_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/tenant/usage")).status_code == 401


async def test_only_owners_and_admins_are_managers(db_session: AsyncSession) -> None:
    # In P0 everyone acts in their own personal tenant as owner, so the 403 branch is
    # not reachable over HTTP yet; exercise the dependency directly.
    tenant_id = await make_tenant(db_session)
    tenant = await db_session.get(Tenant, tenant_id)
    assert tenant is not None
    users = {}
    for role in ("owner", "admin", "member"):
        user = User(email=f"{role}@example.com", password_hash="x")
        db_session.add(user)
        await db_session.flush()
        db_session.add(TenantMember(tenant_id=tenant_id, user_id=user.id, role=role))
        users[role] = user
    outsider = User(email="outsider@example.com", password_hash="x")
    db_session.add(outsider)
    await db_session.commit()

    for role in ("owner", "admin"):
        await require_tenant_manager(users[role], tenant, db_session)
    for user in (users["member"], outsider):
        with pytest.raises(HTTPException) as exc_info:
            await require_tenant_manager(user, tenant, db_session)
        assert exc_info.value.status_code == 403


async def test_usage_days_is_bounded(client: AsyncClient) -> None:
    await register(client, "owner@example.com")
    for days in (0, 91):
        assert (await client.get("/tenant/usage", params={"days": days})).status_code == 422


# --- /usage/estimates ---------------------------------------------------------------------


def by_feature(body: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {f["feature"]: f["calls"] for f in body["features"]}


async def test_estimates_average_recent_successful_calls(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "owner@example.com")
    tenant_id = await tenant_of(db_session, "owner@example.com")
    now = datetime.now(UTC)
    await add_usage(
        db_session,
        record(tenant_id, input_tokens=1000, output_tokens=100),
        record(tenant_id, input_tokens=3000, output_tokens=300),
        # Failed calls and calls whose vendor reported no usage don't count.
        record(tenant_id, status="error", input_tokens=0, output_tokens=0),
        record(tenant_id, input_tokens=0, output_tokens=0),
        record(tenant_id, task="asr", input_tokens=0, output_tokens=0, audio_seconds=8.0),
        record(tenant_id, task="asr", input_tokens=0, output_tokens=0, audio_seconds=12.5),
        record(tenant_id, task="tts", input_tokens=0, output_tokens=0, characters=40),
        record(tenant_id, task="tts", input_tokens=0, output_tokens=0, characters=81),
        at=now,
    )
    # Outside the window of the 20 most recent chat calls.
    old = [record(tenant_id, input_tokens=90_000, output_tokens=1) for _ in range(20)]
    await add_usage(db_session, *old, at=now - timedelta(days=3))
    await add_usage(
        db_session,
        *[record(tenant_id, input_tokens=2000, output_tokens=200) for _ in range(18)],
        at=now - timedelta(days=1),
    )

    response = await client.get("/usage/estimates")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window"] == 20
    features = by_feature(body)
    chat, tools, route, review, reflect, embed = features["chat_message"]
    assert (tools["task"], tools["source"]) == ("chat_tools", "default")
    assert (route["task"], route["timing"]) == ("route", "now")
    assert (review["task"], review["timing"]) == ("writing_review", "now")
    assert chat["task"] == "chat"
    assert (chat["source"], chat["samples"]) == ("history", 20)
    assert (chat["input_tokens"], chat["output_tokens"]) == (2000, 200)
    assert (reflect["task"], reflect["timing"], reflect["source"]) == (
        "reflect",
        "background",
        "default",
    )
    assert embed["source"] == "default"  # embeddings never land in llm_usage
    (asr,) = features["chat_audio"]
    assert (asr["source"], asr["samples"], asr["audio_seconds"]) == ("history", 2, 10.2)
    (tts,) = features["read_aloud"]
    assert (tts["source"], tts["samples"], tts["characters"]) == ("history", 2, 60)
    # No connections yet: nothing would run.
    assert chat["model"] is None and asr["model"] is None


async def test_estimates_are_tenant_scoped_and_open_to_learners(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "other@example.com")
    other = await tenant_of(db_session, "other@example.com")
    await add_usage(db_session, record(other, input_tokens=5000), at=datetime.now(UTC))
    await register(client, "owner@example.com")

    response = await client.get("/usage/estimates")

    assert response.status_code == 200
    (chat, *_) = by_feature(response.json())["chat_message"]
    assert chat["source"] == "default"


async def test_estimates_name_the_model_that_would_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "owner@example.com")
    response = await client.post(
        "/tenant/connections", json={"preset": "deepseek", "api_key": "sk-test-000000"}
    )
    assert response.status_code == 201, response.text

    features = by_feature((await client.get("/usage/estimates")).json())

    assert features["chat_message"][0]["model"] == "deepseek:deepseek-chat"
    assert features["practice_start"][0]["model"] == "deepseek:deepseek-chat"
    # vision only runs on models configured for it; DeepSeek isn't.
    assert features["chat_image"][0]["model"] is None


async def add_call(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    seconds: float,
    replies: list[tuple[int, int]],
    *,
    status: str = "done",
) -> None:
    """A realtime call that lasted `seconds`, with one usage row per reply."""
    user_id = await session.scalar(
        select(TenantMember.user_id).where(TenantMember.tenant_id == tenant_id)
    )
    assert user_id is not None
    conversation = Conversation(tenant_id=tenant_id, user_id=user_id, purpose="realtime")
    session.add(conversation)
    await session.flush()
    session.add(
        SpeakingSession(
            user_id=user_id,
            conversation_id=conversation.id,
            mode="realtime",
            status=status,
            level="B1",
            call_seconds=seconds,
            ended_at=datetime.now(UTC) if status == "done" else None,
        )
    )
    await session.commit()
    await add_usage(
        session,
        *[
            record(
                tenant_id,
                task="realtime",
                conversation_id=conversation.id,
                input_tokens=i,
                output_tokens=o,
            )
            for i, o in replies
        ],
        at=datetime.now(UTC),
    )


async def test_realtime_estimates_are_per_minute_of_call(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "owner@example.com")
    tenant_id = await tenant_of(db_session, "owner@example.com")

    call, _embed, *_after = by_feature((await client.get("/usage/estimates")).json())[
        "realtime_call"
    ]
    assert (call["per"], call["source"]) == ("minute", "default")
    assert (call["input_tokens"], call["output_tokens"]) == (8000, 400)

    # 3 minutes in all: 90k in, 4.5k out -> 30k / 1.5k a minute.
    await add_call(db_session, tenant_id, 60, [(20_000, 1_000), (10_000, 500)])
    await add_call(db_session, tenant_id, 120, [(60_000, 3_000)])
    # Too short to say anything about talking, and a call still going: left out.
    await add_call(db_session, tenant_id, 10, [(90_000, 9_000)])
    await add_call(db_session, tenant_id, 600, [(90_000, 9_000)], status="active")

    call, _embed, *_after = by_feature((await client.get("/usage/estimates")).json())[
        "realtime_call"
    ]

    assert (call["source"], call["samples"]) == ("history", 2)
    assert (call["input_tokens"], call["output_tokens"]) == (30000, 1500)


async def test_estimates_require_login(client: AsyncClient) -> None:
    assert (await client.get("/usage/estimates")).status_code == 401


async def test_usage_shows_members_calls_on_this_accounts_connections(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "member@example.com")
    member_tenant = await tenant_of(db_session, "member@example.com")
    member = await db_session.scalar(select(User).where(User.email == "member@example.com"))
    assert member is not None
    member.display_name = "Alex"
    await register(client, "owner@example.com")  # the client is now logged in as owner
    owner_tenant = await tenant_of(db_session, "owner@example.com")
    now = datetime.now(UTC)
    await add_usage(
        db_session,
        record(owner_tenant),
        # On the owner's connection, counted against the member's quota (ADR 0031 §6).
        record(member_tenant, user_id=member.id, billed_tenant_id=owner_tenant, input_tokens=7),
        # On the member's own connection: none of the owner's business (Q65c).
        record(member_tenant, user_id=member.id, connection_name="mine"),
        at=now,
    )

    response = await client.get("/tenant/usage")

    rows = response.json()["rows"]
    assert [(r["member"], r["connection"], r["input_tokens"]) for r in rows] == [
        (None, "openai", 10),
        ("Alex", "openai", 7),
    ]


# --- /tenant/usage/dashboard --------------------------------------------------------------


async def test_dashboard_totals_series_and_groups(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "member@example.com")
    member_tenant = await tenant_of(db_session, "member@example.com")
    member = await db_session.scalar(select(User).where(User.email == "member@example.com"))
    assert member is not None
    await register(client, "owner@example.com")
    tenant_id = await tenant_of(db_session, "owner@example.com")
    now = datetime.now(UTC)
    await add_usage(
        db_session,
        record(tenant_id, input_tokens=100, output_tokens=20),
        record(tenant_id, task="reflect", background=True, status="error", is_fallback=True),
        record(
            tenant_id,
            task="asr",
            section="asr",
            input_tokens=0,
            output_tokens=0,
            audio_seconds=90.0,
        ),
        record(member_tenant, user_id=member.id, billed_tenant_id=tenant_id, input_tokens=7),
        # On the member's own connection: not this account's.
        record(member_tenant, user_id=member.id, connection_name="mine"),
        at=now,
    )
    await add_usage(db_session, record(tenant_id), at=now - timedelta(days=2))
    await add_usage(db_session, record(tenant_id), at=now - timedelta(days=7))  # out of range

    response = await client.get("/tenant/usage/dashboard", params={"days": 7})

    assert response.status_code == 200
    body = response.json()
    total = body["total"]
    assert (total["calls"], total["errors"], total["fallbacks"]) == (5, 1, 1)
    assert total["input_tokens"] == 100 + 10 + 0 + 7 + 10
    assert total["audio_minutes"] == pytest.approx(1.5)
    assert total["cost"] is None and not body["priced"]
    assert len(body["series"]) == 7
    assert body["series"][-1]["day"] == now.date().isoformat()
    assert [d["calls"] for d in body["series"]] == [0, 0, 0, 0, 1, 0, 4]
    assert [(t["task"], t["background"], t["calls"]) for t in body["tasks"]] == [
        ("chat", False, 3),
        ("asr", False, 1),
        ("reflect", True, 1),
    ]
    assert [(m["connection"], m["calls"]) for m in body["models"]] == [("openai", 5)]
    assert [(m["member"], m["calls"]) for m in body["members"]] == [
        (None, 4),
        ("member@example.com", 1),
    ]


async def test_dashboard_is_for_managers_and_bounded(client: AsyncClient) -> None:
    assert (await client.get("/tenant/usage/dashboard")).status_code == 401
    await register(client, "owner@example.com")
    for days in (0, 91):
        response = await client.get("/tenant/usage/dashboard", params={"days": days})
        assert response.status_code == 422


# --- /tenant/prices -----------------------------------------------------------------------


async def test_prices_start_empty_and_replace_as_a_whole(client: AsyncClient) -> None:
    await register(client, "owner@example.com")
    assert (await client.get("/tenant/prices")).json() == {"currency": "CNY", "prices": []}

    body = {
        "currency": "USD",
        "prices": [
            {"connection": "openai", "model": "gpt-5-mini", "input_per_mtok": 0.25},
            # Nothing entered: dropped.
            {"connection": "deepseek", "model": "deepseek-chat"},
        ],
    }
    response = await client.put("/tenant/prices", json=body)

    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "prices": [
            {
                "connection": "openai",
                "model": "gpt-5-mini",
                "input_per_mtok": 0.25,
                "output_per_mtok": None,
                "per_kchar": None,
                "per_minute": None,
            }
        ],
    }
    response = await client.put("/tenant/prices", json={"currency": "USD", "prices": []})
    assert response.json()["prices"] == []


async def test_prices_are_validated(client: AsyncClient) -> None:
    assert (await client.get("/tenant/prices")).status_code == 401
    await register(client, "owner@example.com")
    price = {"connection": "openai", "model": "m", "input_per_mtok": 1}
    for body in (
        {"currency": "EUR", "prices": []},
        {"currency": "CNY", "prices": [{**price, "input_per_mtok": -1}]},
        {"currency": "CNY", "prices": [price, price]},
    ):
        assert (await client.put("/tenant/prices", json=body)).status_code == 422


async def test_dashboard_costs_use_the_entered_prices(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "owner@example.com")
    tenant_id = await tenant_of(db_session, "owner@example.com")
    await add_usage(
        db_session,
        record(tenant_id, input_tokens=1_000_000, output_tokens=500_000),
        record(tenant_id, connection_name="deepseek", model="deepseek-chat"),
        at=datetime.now(UTC),
    )
    prices = [
        {"connection": "openai", "model": "gpt-5-mini", "input_per_mtok": 2, "output_per_mtok": 8}
    ]
    await client.put("/tenant/prices", json={"currency": "USD", "prices": prices})

    body = (await client.get("/tenant/usage/dashboard", params={"days": 1})).json()

    assert body["priced"] and body["currency"] == "USD"
    assert body["total"]["cost"] == pytest.approx(6)
    assert body["total"]["cost_partial"]  # deepseek has no price
    assert body["series"][-1]["cost"] == pytest.approx(6)
    assert {m["model"]: m["cost"] for m in body["models"]} == {
        "gpt-5-mini": pytest.approx(6),
        "deepseek-chat": None,
    }


# --- /me/usage ----------------------------------------------------------------------------


def by_capability(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["capability"]: c for c in body["capabilities"]}


async def test_my_usage_this_month_without_a_main_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    assert (await client.get("/me/usage")).status_code == 401
    await register(client, "me@example.com")
    tenant_id = await tenant_of(db_session, "me@example.com")
    me = await db_session.scalar(select(User).where(User.email == "me@example.com"))
    assert me is not None
    now = datetime.now(UTC)
    await add_usage(
        db_session,
        record(tenant_id, user_id=me.id, section="llm", input_tokens=100, output_tokens=20),
        # Before sections were recorded: text.
        record(tenant_id, user_id=me.id, input_tokens=5, output_tokens=0),
        record(
            tenant_id,
            user_id=me.id,
            section="tts",
            task="tts",
            input_tokens=0,
            output_tokens=0,
            characters=300,
        ),
        record(
            tenant_id,
            user_id=me.id,
            section="asr",
            task="asr",
            input_tokens=0,
            output_tokens=0,
            audio_seconds=90.0,
        ),
        # Background work with no learner, and another month: not mine.
        record(tenant_id, section="llm"),
        at=now,
    )
    await add_usage(
        db_session,
        record(tenant_id, user_id=me.id, section="llm"),
        at=now.replace(day=1) - timedelta(days=1),
    )
    conversation = Conversation(tenant_id=tenant_id, user_id=me.id, purpose="realtime")
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        SpeakingSession(
            user_id=me.id,
            conversation_id=conversation.id,
            mode="realtime",
            level="B1",
            call_seconds=120,
        )
    )
    await db_session.commit()

    body = (await client.get("/me/usage")).json()

    assert body["month_start"] == now.replace(day=1).date().isoformat()
    assert body["sponsor_name"] is None
    use = by_capability(body)
    assert {c: (u["unit"], u["month"]) for c, u in use.items()} == {
        "text": ("tokens", 125),
        "tts": ("characters", 300),
        "asr": ("minutes", 1.5),
        "pronunciation": ("minutes", 0),
        "realtime": ("minutes", 2),
    }
    assert all(u["quota"] is None for u in use.values())


async def test_my_usage_shows_a_members_quota_left(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client, "owner@example.com")
    owner_tenant = await tenant_of(db_session, "owner@example.com")
    await register(client, "me@example.com")  # logged in as me
    tenant_id = await tenant_of(db_session, "me@example.com")
    me = await db_session.scalar(select(User).where(User.email == "me@example.com"))
    assert me is not None
    db_session.add(
        OrgMembership(
            sponsor_tenant_id=owner_tenant,
            member_user_id=me.id,
            member_tenant_id=tenant_id,
            quotas=Quotas(text=Limit(daily=1000, monthly=5000)).model_dump(),
        )
    )
    await add_usage(
        db_session,
        record(
            tenant_id,
            user_id=me.id,
            section="llm",
            billed_tenant_id=owner_tenant,
            input_tokens=300,
            output_tokens=100,
        ),
        # On my own connection: mine, not the quota's.
        record(tenant_id, user_id=me.id, section="llm", input_tokens=50, output_tokens=0),
        at=datetime.now(UTC),
    )

    body = (await client.get("/me/usage")).json()

    assert body["sponsor_name"] is not None
    text = by_capability(body)["text"]
    assert text["month"] == 450
    assert text["quota"] == {"daily": 1000, "monthly": 5000, "day": 400, "month": 400, "left": 600}
    assert by_capability(body)["tts"]["quota"]["left"] is None


# --- latency stats (ADR 0056 §1) ----------------------------------------------------------


async def test_latency_stats_are_seeded_from_recent_successful_calls(
    db_session: AsyncSession,
) -> None:
    tenant_id = await make_tenant(db_session)
    now = datetime.now(UTC)
    rows = [
        LLMUsage(
            tenant_id=tenant_id,
            task="exercise_critic",
            connection_name="sub2api",
            model="gpt-6.1",
            latency_ms=10_000,
            first_chunk_ms=3_000,
            status="ok",
        )
        for _ in range(2)
    ]
    # Not counted: a failure, an old call, another section.
    rows += [
        LLMUsage(
            tenant_id=tenant_id,
            task="exercise_critic",
            connection_name="sub2api",
            model="gpt-6.1",
            latency_ms=500_000,
            status="stalled",
        ),
        LLMUsage(
            tenant_id=tenant_id,
            task="exercise_critic",
            connection_name="sub2api",
            model="gpt-6.1",
            latency_ms=500_000,
            status="ok",
            created_at=now - timedelta(days=8),
        ),
        LLMUsage(
            tenant_id=tenant_id,
            task="exercise_critic",
            connection_name="sub2api",
            model="gpt-6.1",
            latency_ms=500_000,
            status="ok",
            section="tts",
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    stats = LatencyStats(StallRule(min_samples=2))
    assert await seed_latency_stats(db_session, stats) == 2
    key = LatencyKey(tenant_id, "sub2api", "gpt-6.1", "exercise_critic")
    assert stats.threshold(key, streamed=False, configured=120) == 30
    assert stats.threshold(key, streamed=True, configured=120) == 20
