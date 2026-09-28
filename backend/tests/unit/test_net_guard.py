import asyncio
import ipaddress
from collections.abc import AsyncIterator

import httpcore2
import httpx2
import pytest

from app.providers import net_guard
from app.providers.clients import GuardedChatAnthropic
from app.providers.errors import ProviderConfigError
from app.providers.net_guard import (
    IPAddress,
    is_forbidden_ip,
    make_async_http_client,
    make_blocked_sync_client,
    validate_base_url,
)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata endpoint
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",
        "64:ff9b::7f00:1",  # NAT64 embedding 127.0.0.1 (is_global says True!)
        "64:ff9b::a00:1",  # NAT64 embedding 10.0.0.1
        "2002:7f00:1::1",  # 6to4
    ],
)
def test_forbidden_addresses(address: str) -> None:
    assert is_forbidden_ip(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_allowed(address: str) -> None:
    assert not is_forbidden_ip(ipaddress.ip_address(address))


def stub_dns(monkeypatch: pytest.MonkeyPatch, *answers: str) -> list[str]:
    """Each resolve() call returns the next answer (last one repeats); returns call log."""
    calls: list[str] = []

    async def fake_resolve(host: str, port: int) -> list[IPAddress]:
        calls.append(host)
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            pass
        return [ipaddress.ip_address(answers[min(len(calls), len(answers)) - 1])]

    monkeypatch.setattr(net_guard, "resolve", fake_resolve)
    return calls


# --- save-time validation -------------------------------------------------------------


async def test_public_https_url_is_accepted_and_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_dns(monkeypatch, "93.184.216.34")
    url = await validate_base_url("https://relay.example.com/v1/", allow_private=False)
    assert url == "https://relay.example.com/v1"


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://relay.example.com/v1", "must use https"),
        ("ftp://relay.example.com", "must use https"),
        ("https://user:pw@relay.example.com", "credentials"),
        ("https://relay.example.com/v1?x=1", "query"),
        ("https://127.0.0.1/v1", "non-public"),
        ("https://[::1]/v1", "non-public"),
        ("https://169.254.169.254/latest", "non-public"),
    ],
)
async def test_bad_urls_rejected(url: str, message: str) -> None:
    with pytest.raises(ProviderConfigError, match=message):
        await validate_base_url(url, allow_private=False)


async def test_hostname_resolving_to_private_ip_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_dns(monkeypatch, "10.0.0.5")
    with pytest.raises(ProviderConfigError, match="non-public"):
        await validate_base_url("https://internal.example.com", allow_private=False)


async def test_private_networks_opt_in_allows_local_http() -> None:
    url = await validate_base_url("http://localhost:11434/v1", allow_private=True)
    assert url == "http://localhost:11434/v1"


# --- connect-time guard -----------------------------------------------------------------


@pytest.fixture
async def local_server() -> AsyncIterator[tuple[int, list[bytes]]]:
    """Minimal HTTP server on 127.0.0.1; records raw requests. Path /redirect -> 302."""
    requests: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        raw = await reader.readuntil(b"\r\n\r\n")
        requests.append(raw)
        if raw.startswith(b"GET /redirect"):
            head = b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/\r\nContent-Length: 0"
            writer.write(head + b"\r\n\r\n")
        else:
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield port, requests


async def test_connect_to_loopback_blocked(local_server: tuple[int, list[bytes]]) -> None:
    port, requests = local_server
    async with make_async_http_client(allow_private=False, timeout=5) as client:
        with pytest.raises(httpx2.ConnectError, match="not allowed"):
            await client.get(f"http://127.0.0.1:{port}/")
    assert requests == []  # nothing reached the server


async def test_dns_rebinding_blocked_at_connect_time(
    monkeypatch: pytest.MonkeyPatch, local_server: tuple[int, list[bytes]]
) -> None:
    """Public answer when the tenant saves the URL, loopback when the SDK connects."""
    port, requests = local_server
    stub_dns(monkeypatch, "93.184.216.34", "127.0.0.1")
    await validate_base_url("https://rebind.example.com", allow_private=False)  # passes
    async with make_async_http_client(allow_private=False, timeout=5) as client:
        with pytest.raises(httpx2.ConnectError, match="not allowed"):
            await client.get(f"http://rebind.example.com:{port}/")
    assert requests == []


async def test_connects_to_checked_ip_but_keeps_hostname(
    monkeypatch: pytest.MonkeyPatch, local_server: tuple[int, list[bytes]]
) -> None:
    """The guard dials the IP it checked, while Host (and TLS SNI) keep the hostname."""
    port, requests = local_server
    stub_dns(monkeypatch, "127.0.0.1")
    monkeypatch.setattr(net_guard, "is_forbidden_ip", lambda ip: False)  # pretend it's public
    async with make_async_http_client(allow_private=False, timeout=5) as client:
        response = await client.get(f"http://api.vendor.test:{port}/v1")
    assert response.text == "ok"
    assert f"host: api.vendor.test:{port}".encode() in requests[0].lower()


async def test_redirects_are_not_followed(local_server: tuple[int, list[bytes]]) -> None:
    port, _ = local_server
    async with make_async_http_client(allow_private=True, timeout=5) as client:
        response = await client.get(f"http://127.0.0.1:{port}/redirect")
    assert response.status_code == 302


async def test_proxy_env_vars_are_ignored(
    monkeypatch: pytest.MonkeyPatch, local_server: tuple[int, list[bytes]]
) -> None:
    port, requests = local_server
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    async with make_async_http_client(allow_private=True, timeout=5) as client:
        response = await client.get(f"http://127.0.0.1:{port}/")
    assert response.status_code == 200 and len(requests) == 1


def test_blocked_sync_client_refuses() -> None:
    with pytest.raises(RuntimeError, match="sync model calls are disabled"):
        make_blocked_sync_client().get("https://api.openai.com")


def test_sdks_accept_our_http_client_type() -> None:
    """openai / anthropic SDKs isinstance-check http_client against httpx2 (not httpx)."""
    import anthropic
    import openai

    client = make_async_http_client(allow_private=False, timeout=5)
    assert openai.AsyncOpenAI(api_key="x", http_client=client)._client is client
    assert anthropic.AsyncAnthropic(api_key="x", http_client=client)._client is client


def test_httpx_internal_hook_still_exists() -> None:
    """Regression guard for the private attribute make_async_http_client relies on."""
    transport = httpx2.AsyncHTTPTransport()
    assert isinstance(transport._pool, httpcore2.AsyncConnectionPool)
    assert hasattr(transport._pool, "_network_backend")


# --- Anthropic subclass -------------------------------------------------------------------


def test_guarded_anthropic_uses_injected_client() -> None:
    http_client = make_async_http_client(allow_private=False, timeout=5)
    model = GuardedChatAnthropic(model="claude-x", api_key="sk-test").with_http_client(http_client)
    assert model._async_client._client is http_client
    with pytest.raises(RuntimeError, match="sync model calls are disabled"):
        _ = model._client


def test_guarded_anthropic_requires_client() -> None:
    model = GuardedChatAnthropic(model="claude-x", api_key="sk-test")
    with pytest.raises(RuntimeError, match="with_http_client"):
        _ = model._async_client
