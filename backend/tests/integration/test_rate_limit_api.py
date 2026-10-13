"""Login, signup and invite-code limits over the API (ADR 0035)."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.ratelimit import Limit, RateLimiter
from tests.integration.test_chat_api import login, new_conversation

PASSWORD = "correct horse battery"


def _limits(app: FastAPI, **specs: str) -> None:
    limits = dict(app.state.rate_limiter.limits)
    limits.update({bucket: Limit.parse(spec) for bucket, spec in specs.items()})
    app.state.rate_limiter = RateLimiter(limits)


async def _login(client: AsyncClient, email: str, password: str, ip: str = "1.1.1.1") -> int:
    response = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    return response.status_code


async def test_login_counts_failures_per_ip_and_email(app: FastAPI, client: AsyncClient) -> None:
    _limits(app, login="3/15m")
    await client.post("/auth/register", json={"email": "a@example.com", "password": PASSWORD})
    for _ in range(3):
        assert await _login(client, "A@example.com", "wrong password") == 401

    response = await client.post(
        "/auth/login",
        json={"email": "a@example.com", "password": PASSWORD},
        headers={"X-Forwarded-For": "1.1.1.1"},
    )
    # Refused before the password is checked, even the right one.
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "rate_limited"
    assert 1 <= int(response.headers["Retry-After"]) <= 900
    # Another IP, or another email from this IP, is still let through.
    assert await _login(client, "a@example.com", PASSWORD, ip="2.2.2.2") == 200
    assert await _login(client, "b@example.com", "wrong password") == 401


async def test_successful_login_clears_the_ip_and_email_count(
    app: FastAPI, client: AsyncClient
) -> None:
    _limits(app, login="2/15m")
    await client.post("/auth/register", json={"email": "a@example.com", "password": PASSWORD})
    assert await _login(client, "a@example.com", "wrong password") == 401
    assert await _login(client, "a@example.com", PASSWORD) == 200
    assert await _login(client, "a@example.com", "wrong password") == 401
    assert await _login(client, "a@example.com", "wrong password") == 401
    assert await _login(client, "a@example.com", PASSWORD) == 429


async def test_one_ip_trying_many_emails_is_limited(app: FastAPI, client: AsyncClient) -> None:
    _limits(app, login_ip="3/15m")
    for n in range(3):
        assert await _login(client, f"u{n}@example.com", "wrong password") == 401
    assert await _login(client, "u9@example.com", "wrong password") == 429
    assert await _login(client, "u9@example.com", "wrong password", ip="2.2.2.2") == 401


async def test_one_email_from_many_ips_is_limited(app: FastAPI, client: AsyncClient) -> None:
    _limits(app, login_email="3/15m")
    for n in range(3):
        assert await _login(client, "a@example.com", "wrong password", ip=f"9.9.9.{n}") == 401
    assert await _login(client, "a@example.com", "wrong password", ip="8.8.8.8") == 429


async def test_token_endpoint_shares_the_login_limits(app: FastAPI, client: AsyncClient) -> None:
    _limits(app, login="1/15m")
    assert await _login(client, "a@example.com", "wrong password") == 401
    response = await client.post(
        "/auth/token",
        data={"username": "a@example.com", "password": PASSWORD},
        headers={"X-Forwarded-For": "1.1.1.1"},
    )
    assert response.status_code == 429


async def test_register_is_limited_per_ip(app: FastAPI, client: AsyncClient) -> None:
    _limits(app, signup="2/1h")

    async def register(n: int, ip: str) -> int:
        response = await client.post(
            "/auth/register",
            json={"email": f"r{n}@example.com", "password": PASSWORD},
            headers={"X-Forwarded-For": ip},
        )
        return response.status_code

    assert await register(1, "1.1.1.1") == 201
    assert await register(2, "1.1.1.1") == 201
    assert await register(3, "1.1.1.1") == 429
    assert await register(4, "2.2.2.2") == 201


async def test_invite_codes_share_the_signup_limit(app: FastAPI, client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": "a@example.com", "password": PASSWORD})
    _limits(app, signup="2/1h")
    for _ in range(2):
        response = await client.post("/org/join/preview", json={"code": "nope"})
        assert response.status_code != 429
    response = await client.post("/org/join", json={"code": "nope"})
    assert response.status_code == 429
    assert "Retry-After" in response.headers


async def test_disabled_limiter_lets_everything_through(app: FastAPI, client: AsyncClient) -> None:
    buckets = ("login", "login_ip", "login_email")
    app.state.rate_limiter = RateLimiter({b: Limit(1, 60) for b in buckets}, enabled=False)
    for _ in range(5):
        assert await _login(client, "a@example.com", "wrong password") == 401


# Per-user limits on the endpoints that call models (ADR 0035 §3).


async def _twice(client: AsyncClient, method: str, url: str, **kwargs: Any) -> int:
    first = await client.request(method, url, **kwargs)
    assert first.status_code != 429, first.text
    second = await client.request(method, url, **kwargs)
    return second.status_code


@pytest.mark.parametrize(
    ("bucket", "method", "url", "kwargs"),
    [
        (
            "chat",
            "POST",
            f"/conversations/{uuid.UUID(int=1)}/messages/m1/translate",
            {"json": {"target": "zh"}},
        ),
        ("generate", "POST", "/vocab/words/999999/examples", {}),
        ("generate", "POST", "/memories", {"json": {"content": "I like tea."}}),
        ("tts", "POST", "/speech/tts", {"json": {"text": "Hi.", "language": "en-US"}}),
    ],
)
async def test_model_endpoints_are_limited_per_user(
    app: FastAPI,
    client: AsyncClient,
    bucket: str,
    method: str,
    url: str,
    kwargs: dict[str, Any],
) -> None:
    await login(client)
    _limits(app, **{bucket: "1/1m"})
    assert await _twice(client, method, url, **kwargs) == 429
    # Someone else has their own count.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await login(other, "other@example.com")
        assert (await other.request(method, url, **kwargs)).status_code != 429


async def test_audio_attachments_count_as_speech_to_text(app: FastAPI, client: AsyncClient) -> None:
    await login(client)
    conversation = await new_conversation(client)
    url = f"/conversations/{conversation['id']}/attachments"
    wav = b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(64)
    _limits(app, asr="1/1m", chat="1/1m")
    audio = {"files": {"file": ("a.wav", wav, "application/octet-stream")}}
    assert await _twice(client, "POST", url, **audio) == 429
    # A document is on the chat count, still free.
    text_file = {"files": {"file": ("notes.txt", b"hello", "application/octet-stream")}}
    assert (await client.post(url, **text_file)).status_code == 201
    # A file that isn't accepted calls nothing and isn't counted.
    junk = {"files": {"file": ("x.bin", b"\x00\x01", "application/octet-stream")}}
    assert (await client.post(url, **junk)).status_code == 415
    await app.state.attachment_processor.wait_idle()
