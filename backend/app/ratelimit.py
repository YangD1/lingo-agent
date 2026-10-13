"""In-process rate limits (ADR 0035): a sliding log of hit times per key.

One uvicorn worker (ADR 0025), so a dict in memory is enough; counts reset on restart.
Checking and recording never await, so no lock is needed on the event loop.
"""

import math
import re
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from starlette.requests import HTTPConnection

_SPEC = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*([smh])\s*$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}
# Drop keys with no hits in their window every this many hits.
_SWEEP_EVERY = 1000


@dataclass(frozen=True)
class Limit:
    count: int
    seconds: int

    @classmethod
    def parse(cls, spec: str) -> "Limit":
        """`"20/1m"` → 20 hits per minute; units `s`, `m`, `h`."""
        match = _SPEC.match(spec)
        if match is None:
            raise ValueError(f"rate limit must look like '20/1m', got {spec!r}")
        count, amount, unit = int(match[1]), int(match[2]), match[3]
        if count < 1 or amount < 1:
            raise ValueError(f"rate limit count and window must be positive, got {spec!r}")
        return cls(count, amount * _UNIT_SECONDS[unit])


class RateLimitedError(Exception):
    def __init__(self, bucket: str, retry_after: int) -> None:
        super().__init__(f"rate limited: {bucket}, retry after {retry_after}s")
        self.bucket = bucket
        self.retry_after = retry_after


class RateLimiter:
    """Buckets are named limits; each (bucket, key) keeps at most `count` recent hits."""

    def __init__(
        self,
        limits: Mapping[str, Limit],
        *,
        enabled: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = dict(limits)
        self.enabled = enabled
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._since_sweep = 0

    def check(self, bucket: str, key: str) -> None:
        """Raise RateLimitedError if one more hit would go over, without recording it."""
        if not self.enabled:
            return
        limit = self.limits[bucket]
        hits = self._recent(bucket, key, limit)
        if hits is not None and len(hits) >= limit.count:
            wait = hits[0] + limit.seconds - self._clock()
            raise RateLimitedError(bucket, max(1, math.ceil(wait)))

    def record(self, bucket: str, key: str) -> None:
        if not self.enabled:
            return
        limit = self.limits[bucket]
        hits = self._hits.setdefault((bucket, key), deque(maxlen=limit.count))
        hits.append(self._clock())
        self._since_sweep += 1
        if self._since_sweep >= _SWEEP_EVERY:
            self.sweep()

    def hit(self, bucket: str, key: str) -> None:
        """Check, then record: the usual one-call form."""
        self.check(bucket, key)
        self.record(bucket, key)

    def reset(self, bucket: str, key: str) -> None:
        self._hits.pop((bucket, key), None)

    def sweep(self) -> None:
        """Forget keys whose hits have all left their window."""
        self._since_sweep = 0
        now = self._clock()
        stale = [k for k, hits in self._hits.items() if hits[-1] <= now - self.limits[k[0]].seconds]
        for k in stale:
            del self._hits[k]

    def _recent(self, bucket: str, key: str, limit: Limit) -> deque[float] | None:
        hits = self._hits.get((bucket, key))
        if hits is None:
            return None
        cutoff = self._clock() - limit.seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits


def client_ip(conn: HTTPConnection) -> str:
    """The rightmost X-Forwarded-For entry, else the peer address (ADR 0035 §4).

    Next's rewrite passes the header on unchanged, so it is only trustworthy behind a
    reverse proxy that overwrites it (Caddy, task 71).
    """
    forwarded = conn.headers.get("x-forwarded-for", "")
    entries = [part.strip() for part in forwarded.split(",") if part.strip()]
    if entries:
        return entries[-1]
    return conn.client.host if conn.client is not None else "unknown"
