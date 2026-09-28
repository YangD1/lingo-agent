"""SSRF protection for tenant-supplied provider base_urls (ADR 0004 §4).

Two layers:
1. `validate_base_url` - when a tenant saves a connection: scheme, no credentials in the
   URL, and every address the host resolves to must be public.
2. `GuardedNetworkBackend` - on every TCP connect: resolve again, check again, and
   connect to the *checked* IP. Checking only at save time is not enough: the SDK
   resolves DNS itself, and an attacker-controlled domain can answer with a public IP
   first and 127.0.0.1 later (DNS rebinding). TLS still uses the URL's hostname for SNI
   and certificate checks, because httpcore takes `server_hostname` from the request
   origin, not from the address we connect to.

Built on httpx2/httpcore2 (API-identical forks of httpx/httpcore) because the openai and
anthropic SDKs switched to them and reject plain httpx clients via isinstance checks.
"""

import ipaddress
import socket
from collections.abc import Iterable

import anyio
import httpcore2
import httpx2

from app.providers.errors import ProviderConfigError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class ForbiddenDestinationError(httpcore2.ConnectError):
    """Raised on connect; httpx maps it to httpx2.ConnectError, SDKs to connection errors."""


def is_forbidden_ip(ip: IPAddress) -> bool:
    """Loopback, private, link-local (incl. cloud metadata), CGNAT, reserved, multicast..."""
    if isinstance(ip, ipaddress.IPv6Address):
        # IPv4 embedded in IPv6: judge the IPv4 address it actually reaches.
        if ip.ipv4_mapped is not None:
            return is_forbidden_ip(ip.ipv4_mapped)
        if ip in _NAT64:  # `is_global` is True for NAT64 even when it embeds 127.0.0.1
            return is_forbidden_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return not ip.is_global or ip.is_multicast


async def resolve(host: str, port: int) -> list[IPAddress]:
    """All addresses `host` resolves to (module-level so tests can stub DNS)."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos))


async def validate_base_url(url: str, *, allow_private: bool) -> str:
    """Check a tenant-supplied base_url; returns it normalized (no trailing slash)."""
    try:
        parsed = httpx2.URL(url)
    except httpx2.InvalidURL as exc:
        raise ProviderConfigError(f"invalid URL: {exc}") from exc
    allowed_schemes = {"https", "http"} if allow_private else {"https"}
    if parsed.scheme not in allowed_schemes:
        raise ProviderConfigError(f"base_url must use {' or '.join(sorted(allowed_schemes))}")
    if not parsed.host:
        raise ProviderConfigError("base_url needs a host")
    if parsed.userinfo:
        raise ProviderConfigError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ProviderConfigError("base_url must not contain a query or fragment")
    if not allow_private:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = await resolve(parsed.host, port)
        except OSError as exc:
            raise ProviderConfigError(f"cannot resolve host {parsed.host!r}") from exc
        if not addresses or any(is_forbidden_ip(ip) for ip in addresses):
            raise ProviderConfigError(
                f"host {parsed.host!r} resolves to a non-public address; private networks "
                "are disabled on this server (PROVIDER_ALLOW_PRIVATE_NETWORKS)"
            )
    return str(parsed).rstrip("/")


class GuardedNetworkBackend(httpcore2.AsyncNetworkBackend):
    """Resolves, checks, then connects to the checked IP (defeats DNS rebinding)."""

    def __init__(self, inner: httpcore2.AsyncNetworkBackend | None = None) -> None:
        self._inner = inner or httpcore2.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (signature fixed by httpcore)
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        try:
            with anyio.fail_after(timeout):
                addresses = await resolve(host, port)
        except (OSError, TimeoutError) as exc:
            raise httpcore2.ConnectError(f"cannot resolve {host!r}: {exc}") from exc
        # Strict: any forbidden answer rejects the host, rather than silently picking
        # the public one.
        if not addresses or any(is_forbidden_ip(ip) for ip in addresses):
            raise ForbiddenDestinationError(f"destination {host!r} is not allowed")
        last_error: Exception | None = None
        for ip in addresses:
            try:
                return await self._inner.connect_tcp(
                    str(ip), port, timeout, local_address, socket_options
                )
            except httpcore2.ConnectError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 (signature fixed by httpcore)
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        raise ForbiddenDestinationError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def make_async_http_client(*, allow_private: bool, timeout: float | None) -> httpx2.AsyncClient:
    """HTTP client for model SDKs talking to tenant-controlled endpoints."""
    transport = httpx2.AsyncHTTPTransport(trust_env=False)
    if not allow_private:
        # httpx2 has no public hook for the network backend; its httpcore2 pool reads
        # `_network_backend` when opening connections. Guarded by a regression test.
        transport._pool._network_backend = GuardedNetworkBackend()
    return httpx2.AsyncClient(
        transport=transport,
        timeout=timeout,
        # Redirects could bounce a vetted request to an internal address.
        follow_redirects=False,
        # Ignore HTTP(S)_PROXY: a proxy would receive the request, bypassing the IP check.
        trust_env=False,
    )


class _SyncCallsDisabled(httpx2.BaseTransport):
    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        raise RuntimeError("sync model calls are disabled; use the async API (ainvoke/astream)")


def make_blocked_sync_client() -> httpx2.Client:
    """Sync client that always fails, so no unguarded sync code path can reach the network."""
    return httpx2.Client(transport=_SyncCallsDisabled())
