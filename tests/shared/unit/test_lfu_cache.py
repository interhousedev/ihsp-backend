"""The small in-house LFU cache: least-frequently-used eviction, ties by oldest."""

from app.shared.lfu_cache import LFUCache

import pytest


def test_get_returns_stored_value_and_default_when_missing() -> None:
    cache: LFUCache[str, int] = LFUCache(maxsize=2)
    cache["a"] = 1
    assert cache.get("a") == 1
    assert cache.get("missing") is None
    assert cache.get("missing", 7) == 7


def test_contains_and_len_do_not_count_as_use() -> None:
    cache: LFUCache[str, int] = LFUCache(maxsize=2)
    cache["a"] = 1
    cache["b"] = 2
    assert "a" in cache
    assert "c" not in cache
    assert len(cache) == 2
    # "a" was only probed, never read, so it keeps frequency one and is evicted.
    cache.get("b")
    cache.get("b")
    cache["c"] = 3
    assert "a" not in cache
    assert "b" in cache
    assert "c" in cache


def test_evicts_least_frequently_used() -> None:
    cache: LFUCache[str, int] = LFUCache(maxsize=2)
    cache["hot"] = 1
    cache["cold"] = 2
    for _ in range(3):
        cache.get("hot")
    cache["new"] = 3
    assert "cold" not in cache
    assert "hot" in cache
    assert "new" in cache


def test_ties_are_broken_by_oldest_access() -> None:
    cache: LFUCache[str, int] = LFUCache(maxsize=2)
    cache["a"] = 1
    cache["b"] = 2
    cache.get("b")
    cache.get("a")  # both at frequency two; "b" was touched longest ago
    cache["c"] = 3
    assert "b" not in cache
    assert "a" in cache
    assert "c" in cache


def test_overwrite_keeps_size_and_updates_value() -> None:
    cache: LFUCache[str, int] = LFUCache(maxsize=1)
    cache["a"] = 1
    cache["a"] = 2
    assert len(cache) == 1
    assert cache.get("a") == 2


def test_never_exceeds_maxsize() -> None:
    cache: LFUCache[int, int] = LFUCache(maxsize=4)
    for i in range(50):
        cache[i] = i
        cache.get(i)
    assert len(cache) == 4


def test_rejects_non_positive_maxsize() -> None:
    with pytest.raises(ValueError):
        LFUCache(maxsize=0)
