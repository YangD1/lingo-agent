from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant, TenantMember, User
from app.deps import AUTH_COOKIE

EMAIL = "Learner@Example.com"
PASSWORD = "correct horse battery"


async def register(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> None:
    response = await client.post(
        "/auth/register", json={"email": email, "password": password, "display_name": "Lee"}
    )
    assert response.status_code == 201, response.text


async def test_register_sets_httponly_cookie_and_logs_in(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 201
    assert response.json()["email"] == "learner@example.com"  # normalized

    set_cookie = response.headers["set-cookie"].lower()
    assert f"{AUTH_COOKIE}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "secure" not in set_cookie  # dev/test runs on plain http

    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "learner@example.com"
    assert me.json()["tenant"]["kind"] == "personal"


async def test_register_creates_personal_tenant_with_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client)
    user = await db_session.scalar(select(User))
    assert user is not None
    member = await db_session.scalar(select(TenantMember).where(TenantMember.user_id == user.id))
    assert member is not None and member.role == "owner"
    tenant = await db_session.get(Tenant, member.tenant_id)
    assert tenant is not None and tenant.kind == "personal" and tenant.name == "Lee"
    assert user.password_hash.startswith("$argon2id$")


async def test_duplicate_email_is_case_insensitive(client: AsyncClient) -> None:
    await register(client)
    response = await client.post(
        "/auth/register", json={"email": "LEARNER@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409


async def test_register_validates_input(client: AsyncClient) -> None:
    short = await client.post("/auth/register", json={"email": EMAIL, "password": "short"})
    assert short.status_code == 422
    bad_email = await client.post("/auth/register", json={"email": "nope", "password": PASSWORD})
    assert bad_email.status_code == 422


async def test_login_errors_do_not_reveal_which_emails_exist(client: AsyncClient) -> None:
    await register(client)
    client.cookies.clear()
    wrong_password = await client.post("/auth/login", json={"email": EMAIL, "password": "x" * 9})
    unknown_email = await client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_login_then_logout(client: AsyncClient) -> None:
    await register(client)
    client.cookies.clear()
    assert (await client.get("/auth/me")).status_code == 401

    login = await client.post(
        "/auth/login", json={"email": "learner@EXAMPLE.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert (await client.get("/auth/me")).status_code == 200

    logout = await client.post("/auth/logout")
    assert logout.status_code == 204
    assert f'{AUTH_COOKIE}=""' in logout.headers["set-cookie"] or "max-age=0" in (
        logout.headers["set-cookie"].lower()
    )
    assert (await client.get("/auth/me")).status_code == 401


async def test_bearer_token_flow_for_non_browser_clients(client: AsyncClient) -> None:
    await register(client)
    client.cookies.clear()
    response = await client.post("/auth/token", data={"username": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    token = response.json()["access_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


async def test_garbage_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_inactive_user_cannot_log_in_or_use_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(client)
    user = await db_session.scalar(select(User))
    assert user is not None
    user.is_active = False
    await db_session.commit()

    assert (await client.get("/auth/me")).status_code == 401  # existing cookie stops working
    client.cookies.clear()
    login = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 401
