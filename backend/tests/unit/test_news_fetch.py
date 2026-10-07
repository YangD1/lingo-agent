"""Fetching a feed: conditional requests, redirects, limits, errors (task 41.2; Q41f, Q41h)."""

import ipaddress
from collections.abc import Callable

import httpx2
import pytest

from app.providers import net_guard
from app.services.news import fetch
from app.services.news.fetch import FeedFetchError, Fetched, fetch_feed, make_feed_client

URL = "https://feeds.example/rss"
Handler = Callable[[httpx2.Request], httpx2.Response]


def client(handle: Handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


async def get(handle: Handler, url: str = URL, *, resolve: bool = False, **kw: str) -> Fetched:
    async with client(handle) as c:
        return await fetch_feed(
            c, url, etag=kw.get("etag"), last_modified=kw.get("last_modified"), resolve=resolve
        )


async def error(handle: Handler, url: str = URL, *, resolve: bool = False) -> str:
    with pytest.raises(FeedFetchError) as caught:
        await get(handle, url, resolve=resolve)
    return caught.value.code


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Host -> address, for fetches through a proxy (which check addresses first)."""
    table = {"feeds.example": "93.184.216.34", "inside.example": "10.0.0.5"}

    async def resolve(host: str, port: int) -> list[net_guard.IPAddress]:
        if host == "unknown.example":
            raise OSError("Temporary failure in name resolution")
        return [ipaddress.ip_address(table.get(host, host))]

    monkeypatch.setattr(net_guard, "resolve", resolve)
    return table


async def test_a_fetch_sends_validators_and_returns_new_ones() -> None:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200, content=b"<rss/>", headers={"ETag": '"v2"', "Last-Modified": "Thu, 08 Oct"}
        )

    fetched = await get(handle, etag='"v1"', last_modified="Wed, 07 Oct")
    assert fetched == Fetched(b"<rss/>", '"v2"', "Thu, 08 Oct")
    (request,) = seen
    assert request.headers["If-None-Match"] == '"v1"'
    assert request.headers["If-Modified-Since"] == "Wed, 07 Oct"
    assert request.headers["User-Agent"].startswith("lingo-agent/")


async def test_not_modified_keeps_the_old_validators() -> None:
    fetched = await get(lambda _: httpx2.Response(304), etag='"v1"', last_modified="Wed")
    assert fetched == Fetched(None, '"v1"', "Wed")


async def test_an_over_long_validator_is_dropped() -> None:
    fetched = await get(lambda _: httpx2.Response(200, content=b"x", headers={"ETag": "e" * 501}))
    assert fetched.etag is None


async def test_redirects_are_followed_and_capped() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/rss":
            return httpx2.Response(301, headers={"Location": "/feed.xml"})
        return httpx2.Response(200, content=b"moved")

    assert (await get(handle)).content == b"moved"

    def loop(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"Location": "/again"})

    assert await error(loop) == "too_many_redirects"


@pytest.mark.usefixtures("dns")
async def test_through_a_proxy_each_hop_is_checked() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"Location": "http://inside.example/admin"})

    assert await error(handle, resolve=True) == "forbidden_destination"
    assert await error(handle, "http://127.0.0.1/rss", resolve=True) == "forbidden_destination"
    for internal in ("http://localhost/rss", "http://router/rss", "http://nas.local/rss"):
        assert await error(handle, internal, resolve=True) == "forbidden_destination"


@pytest.mark.usefixtures("dns")
async def test_through_a_proxy_a_name_local_dns_cannot_find_is_left_to_the_proxy() -> None:
    fetched = await get(
        lambda _: httpx2.Response(200, content=b"ok"), "https://unknown.example/rss", resolve=True
    )
    assert fetched.content == b"ok"


async def test_only_plain_http_addresses() -> None:
    def never(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request expected")

    assert await error(never, "ftp://feeds.example/rss") == "invalid_url"
    assert await error(never, "https://user:pw@feeds.example/rss") == "invalid_url"
    assert await error(never, "not a url") == "invalid_url"


async def test_status_and_size_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await error(lambda _: httpx2.Response(404)) == "http_404"
    monkeypatch.setattr(fetch, "MAX_BYTES", 10)
    big = b"x" * 11
    assert await error(lambda _: httpx2.Response(200, content=big)) == "too_large"

    # No Content-Length: counted while streaming.
    async def chunks():  # type: ignore[no-untyped-def]
        for _ in range(3):
            yield b"xxxx"

    assert await error(lambda _: httpx2.Response(200, content=chunks())) == "too_large"


async def test_network_errors_become_codes() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    def refused(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    def forbidden(request: httpx2.Request) -> httpx2.Response:
        try:
            raise net_guard.ForbiddenDestinationError("private")
        except net_guard.ForbiddenDestinationError as exc:
            raise httpx2.ConnectError("blocked", request=request) from exc

    assert await error(timeout) == "timeout"
    assert await error(refused) == "network"
    assert await error(forbidden) == "forbidden_destination"


async def test_the_client_uses_the_proxy_only_when_set() -> None:
    async with make_feed_client("") as direct:
        pool = direct._transport._pool  # type: ignore[attr-defined]
        assert isinstance(pool._network_backend, net_guard.GuardedNetworkBackend)
    async with make_feed_client("http://127.0.0.1:7890") as proxied:
        assert not proxied.follow_redirects
        assert proxied._mounts  # the proxy transport
