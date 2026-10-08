"""Small helpers shared by the learning tests."""

from typing import Any

# Keys that carry correctness data; they must never reach a student before grading.
FORBIDDEN_KEYS = {"correct", "answer", "explanation", "accepted", "regex", "tolerance"}


def keys_of(value: Any) -> set[str]:
    """Collect every dict key in a nested structure."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list | tuple):
        return {k for v in value for k in keys_of(v)}
    return set()
