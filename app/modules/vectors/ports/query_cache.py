"""Port: short-lived memory of question vectors."""

from collections.abc import Sequence
from typing import Protocol


class QueryCache(Protocol):
    """Question text -> vector, for a day (same question, same vector)."""

    async def get(self, key: str) -> list[float] | None:
        """The cached vector, if any."""
        ...

    async def put(self, key: str, values: Sequence[float], ttl_seconds: int) -> None:
        """Remember a vector."""
        ...
