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

    def get_or_create(self, key: K, factory: Callable[[], V]) -> V:
        now = self._clock()
        hit = self._data.get(key)
        if hit is not None and hit[0] > now:
            self._data.move_to_end(key)
            return hit[1]
        value = factory()
        self._data[key] = (now + self._ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)
        return value

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
