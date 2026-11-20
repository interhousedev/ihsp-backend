"""A small least-frequently-used cache for one process.

Each read or write bumps the key's use count and stamps it with the current tick.
When a new key arrives at a full cache, the key with the lowest count is evicted;
among equal counts the one with the oldest stamp goes first. Membership tests and
``len`` do not count as use. Eviction scans the entries, which is fine for the small
bounded caches this serves.
"""

from collections.abc import Hashable
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

_MISSING: object = object()


class LFUCache(Generic[K, V]):
    """A bounded mapping that evicts its least frequently used entry."""

    def __init__(self, maxsize: int) -> None:
        """Hold at most ``maxsize`` entries."""
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self._maxsize = maxsize
        self._values: dict[K, V] = {}
        self._uses: dict[K, int] = {}
        self._stamps: dict[K, int] = {}
        self._tick = 0

    def __len__(self) -> int:
        """Number of entries held."""
        return len(self._values)

    def __contains__(self, key: object) -> bool:
        """True when the key is held; this does not count as a use."""
        return key in self._values

    def __getitem__(self, key: K) -> V:
        """Return the value and count a use; KeyError when absent."""
        value = self._touch(key)
        if value is _MISSING:
            raise KeyError(key)
        return value  # type: ignore[return-value]

    def get(self, key: K, default: V | None = None) -> V | None:
        """Return the value and count a use, or ``default`` when absent."""
        value = self._touch(key)
        return default if value is _MISSING else value  # type: ignore[return-value]

    def __setitem__(self, key: K, value: V) -> None:
        """Store the value, evicting the least frequently used entry when full."""
        if key not in self._values and len(self._values) >= self._maxsize:
            self._evict()
        self._values[key] = value
        self._stamp(key, fresh=key not in self._uses)

    def _touch(self, key: K) -> object:
        if key not in self._values:
            return _MISSING
        self._stamp(key, fresh=False)
        return self._values[key]

    def _stamp(self, key: K, *, fresh: bool) -> None:
        self._tick += 1
        self._uses[key] = 1 if fresh else self._uses.get(key, 0) + 1
        self._stamps[key] = self._tick

    def _evict(self) -> None:
        victim = min(self._values, key=lambda k: (self._uses[k], self._stamps[k]))
        del self._values[victim]
        del self._uses[victim]
        del self._stamps[victim]
