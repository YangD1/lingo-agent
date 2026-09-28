"""Every error body is {"detail": {"code", "message"}} so the UI can localize by code."""

import uuid
from typing import Any

from httpx import AsyncClient, Response

from tests.integration.test_auth_api import EMAIL, PASSWORD, register


def error(response: Response, status: int) -> dict[str, Any]:
    assert response.status_code == status, response.text
    detail: dict[str, Any] = response.json()["detail"]
    assert isinstance(detail["message"], str) and detail["message"]
    return detail


async def test_domain_errors_carry_stable_codes(client: AsyncClient) -> None:
    unauthenticated = await client.get("/auth/me")
    assert error(unauthenticated, 401)["code"] == "not_authenticated"
    assert unauthenticated.headers["www-authenticate"] == "Bearer"

    await register(client)
    taken = await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert error(taken, 409)["code"] == "email_taken"

    wrong = await client.post("/auth/login", json={"email": EMAIL, "password": "wrong password"})
    assert error(wrong, 401)["code"] == "invalid_credentials"

    missing = await client.get(f"/conversations/{uuid.uuid4()}/messages")
    assert error(missing, 404)["code"] == "conversation_not_found"

    connection = await client.delete(f"/tenant/connections/{uuid.uuid4()}")
    assert error(connection, 404)["code"] == "connection_not_found"

    route = await client.delete("/tenant/routes/llm/chat")
    assert error(route, 404)["code"] == "route_not_found"


async def test_validation_errors_keep_field_details(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json={"email": EMAIL, "password": "short"})

    detail = error(response, 422)
    assert detail["code"] == "validation_error"
    assert [e["loc"] for e in detail["errors"]] == [["body", "password"]]


async def test_framework_errors_are_wrapped(client: AsyncClient) -> None:
    unknown = await client.get("/no-such-route")
    assert error(unknown, 404) == {"code": "http_404", "message": "Not Found"}

    wrong_method = await client.put("/auth/login")
    assert error(wrong_method, 405)["code"] == "http_405"
