"""Fetching a feed over HTTP (ADR 0024 §2, §6; Q41f, Q41h).

Feed addresses come from learners, so every fetch is guarded against reaching private
networks: directly through `net_guard` (checked on every connect), or through
`FEED_HTTP_PROXY` with the address checked before each request instead. Redirects are
followed here, one hop at a time, so each new address is checked too.
"""

from dataclasses import dataclass

import httpx2

from app.providers import net_guard

USER_AGENT = "lingo-agent/0.1 (+https://github.com/YangD1/lingo-agent)"
TIMEOUT_SECONDS = 20.0
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
# Names that only mean something inside a network; refused before going to the proxy.
_INTERNAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")


class FeedFetchError(Exception):
    """Why a fetch failed, as a short code stored on the feed (`feeds.last_error`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Fetched:
    # None: the feed has not changed since `etag` / `last_modified` (304).
    content: bytes | None
    etag: str | None
    last_modified: str | None


def make_feed_client(proxy: str) -> httpx2.AsyncClient:
    if not proxy:
        return net_guard.make_async_http_client(allow_private=False, timeout=TIMEOUT_SECONDS)
    return httpx2.AsyncClient(
        proxy=proxy, timeout=TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
    )


async def check_address(url: httpx2.URL, *, resolve: bool) -> None:
    """http(s), a host, no credentials; with `resolve`, only public addresses."""
    if url.scheme not in ("http", "https") or not url.host:
        raise FeedFetchError("invalid_url")
    if url.userinfo:
        raise FeedFetchError("invalid_url")
    if not resolve:
        return
    host = url.host.lower().rstrip(".")
    if "." not in host or host.endswith(_INTERNAL_SUFFIXES):
        raise FeedFetchError("forbidden_destination")
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        addresses = await net_guard.resolve(host, port)
    except OSError:
        # Unknown to local DNS (some networks only reach a site through the proxy):
        # the proxy resolves it. No weaker than the DNS rebinding already accepted.
        return
    if not addresses or any(net_guard.is_forbidden_ip(ip) for ip in addresses):
        raise FeedFetchError("forbidden_destination")


def _fit(value: str | None, limit: int) -> str | None:
    # A validator too long for its column is dropped: the next fetch is unconditional.
    return value if value and len(value) <= limit else None


def _is_forbidden(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, net_guard.ForbiddenDestinationError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


async def fetch_feed(
    client: httpx2.AsyncClient,
    url: str,
    *,
    etag: str | None,
    last_modified: str | None,
    resolve: bool,
) -> Fetched:
    """GET the feed, conditionally; `resolve` when `client` goes through a proxy."""
    try:
        target = httpx2.URL(url)
    except httpx2.InvalidURL as exc:
        raise FeedFetchError("invalid_url") from exc
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, */*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    for _ in range(MAX_REDIRECTS + 1):
        await check_address(target, resolve=resolve)
        try:
            async with client.stream("GET", target, headers=headers) as response:
                # Before redirects: httpx counts 304 as one.
                if response.status_code == 304:
                    return Fetched(None, etag, last_modified)
                if response.is_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise FeedFetchError(f"http_{response.status_code}")
                    target = target.join(location)
                    continue
                if response.status_code >= 400:
                    raise FeedFetchError(f"http_{response.status_code}")
                length = response.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > MAX_BYTES:
                    raise FeedFetchError("too_large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise FeedFetchError("too_large")
                return Fetched(
                    bytes(body),
                    _fit(response.headers.get("ETag"), 500),
                    _fit(response.headers.get("Last-Modified"), 100),
                )
        except httpx2.TimeoutException as exc:
            raise FeedFetchError("timeout") from exc
        except httpx2.HTTPError as exc:
            raise FeedFetchError(
                "forbidden_destination" if _is_forbidden(exc) else "network"
            ) from exc
    raise FeedFetchError("too_many_redirects")
