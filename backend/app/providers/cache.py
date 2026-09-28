import time
from collections import OrderedDict
from collections.abc import Callable, Hashable


class TTLCache[K: Hashable, V]:
    """Small LRU cache with per-entry expiry. Not thread-safe; used from the event loop."""

    def __init__(
        self, maxsize: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._clock = clock

    def get(self, key: K) -> V | None:
        hit = self._data.get(key)
        if hit is None or hit[0] <= self._clock():
            return None
        self._data.move_to_end(key)
        return hit[1]

    def put(self, key: K, value: V) -> None:
        self._data[key] = (self._clock() + self._ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def get_or_create(self, key: K, factory: Callable[[], V]) -> V:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = factory()
        self.put(key, value)
        return value

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
