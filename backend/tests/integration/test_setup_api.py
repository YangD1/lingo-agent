"""The setup guide (ADR 0042): step states from real settings, finishing, the name."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models import User
from tests.conftest import run_alembic
from tests.integration.test_advice_candidates import placement
from tests.integration.test_chat_send import connect, login

NOTHING = {"profile": False, "model": False, "goals": False, "tutor": False, "placement": False}


async def test_endpoints_require_login(client: AsyncClient) -> None:
    assert (await client.get("/me/setup")).status_code == 401
    assert (await client.post("/me/setup/complete")).status_code == 401
    assert (await client.patch("/auth/me", json={"display_name": "Lee"})).status_code == 401


async def test_a_new_account_is_sent_to_the_guide(client: AsyncClient) -> None:
    await login(client)
    me = (await client.get("/auth/me")).json()
    assert me["user"]["setup_completed_at"] is None
    assert (await client.get("/me/setup")).json() == {"completed_at": None, "steps": NOTHING}


async def test_steps_follow_what_is_set_up(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    user = await db_session.scalar(select(User))
    assert user is not None

    assert (await client.patch("/auth/me", json={"display_name": " Lee "})).json()[
        "display_name"
    ] == "Lee"
    await connect(client, "deepseek")
    response = await client.patch("/profile", json={"daily_minutes": 20})
    assert response.status_code == 200
    assert (await client.put("/tutor", json={"name": "Momo"})).status_code == 200
    db_session.add(placement(user.id, datetime.now(UTC)))
    await db_session.commit()

    steps = (await client.get("/me/setup")).json()["steps"]
    assert steps == {key: True for key in NOTHING}


async def test_explanation_language_alone_counts_as_the_first_step(client: AsyncClient) -> None:
    await login(client)
    await client.patch("/profile", json={"explanation_language": "zh"})
    steps = (await client.get("/me/setup")).json()["steps"]
    assert steps == {**NOTHING, "profile": True}


async def test_an_open_placement_test_is_not_done(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    user = await db_session.scalar(select(User))
    assert user is not None
    db_session.add(placement(user.id, None))
    await db_session.commit()
    assert (await client.get("/me/setup")).json()["steps"]["placement"] is False


async def test_finishing_is_kept_and_can_be_repeated(client: AsyncClient) -> None:
    await login(client)
    first = (await client.post("/me/setup/complete")).json()["completed_at"]
    assert first is not None
    assert (await client.get("/auth/me")).json()["user"]["setup_completed_at"] == first
    again = (await client.post("/me/setup/complete")).json()["completed_at"]
    assert again >= first


async def test_a_blank_name_is_cleared(client: AsyncClient) -> None:
    await login(client)
    await client.patch("/auth/me", json={"display_name": "Lee"})
    body = (await client.patch("/auth/me", json={"display_name": "  "})).json()
    assert body["display_name"] is None
    assert (await client.patch("/auth/me", json={"email": "x@example.com"})).status_code == 422


async def test_accounts_made_before_the_guide_skip_it(db_engine: AsyncEngine) -> None:
    """Q82d: the migration marks existing accounts as set up."""
    user_id = uuid.uuid4()
    async with db_engine.connect() as conn:
        await conn.run_sync(run_alembic, "0e400aeda096", downgrade=True)
        await conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        await conn.commit()
        await conn.run_sync(run_alembic, "head")
        done = await conn.scalar(
            text("SELECT setup_completed_at = created_at FROM users WHERE id = :id"),
            {"id": user_id},
        )
        await conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await conn.commit()
    assert done is True
