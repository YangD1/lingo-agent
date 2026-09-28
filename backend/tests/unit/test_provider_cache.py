from app.providers.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_hit_miss_and_expiry() -> None:
    clock = FakeClock()
    cache: TTLCache[str, int] = TTLCache(maxsize=10, ttl_seconds=5, clock=clock)
    calls: list[int] = []

    def factory() -> int:
        calls.append(1)
        return len(calls)

    assert cache.get_or_create("a", factory) == 1
    assert cache.get_or_create("a", factory) == 1  # hit
    clock.now = 6
    assert cache.get_or_create("a", factory) == 2  # expired -> rebuilt


def test_lru_eviction() -> None:
    cache: TTLCache[str, str] = TTLCache(maxsize=2, ttl_seconds=100)
    cache.get_or_create("a", lambda: "a")
    cache.get_or_create("b", lambda: "b")
    cache.get_or_create("a", lambda: "never")  # touch a: b is now least recent
    cache.get_or_create("c", lambda: "c")
    assert len(cache) == 2
    assert cache.get_or_create("a", lambda: "rebuilt") == "a"
    assert cache.get_or_create("b", lambda: "rebuilt") == "rebuilt"
