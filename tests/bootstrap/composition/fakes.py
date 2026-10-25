"""Fake module services for the composition adapters: recording `execute` methods."""

from typing import Any


class FakeUseCase:
    """A use case that records its calls and returns canned results in turn.

    With several results the n-th call returns the n-th one; the last result repeats.
    """

    def __init__(self, *results: Any) -> None:
        """Keep the results."""
        self.results = list(results)
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Record the call and return the next result."""
        index = min(len(self.calls), len(self.results) - 1)
        self.calls.append((args, kwargs))
        return self.results[index]


class FakeFilesApi:
    """FilesApi with only `search_text`."""

    def __init__(self, hits: list[dict[str, Any]] | None = None) -> None:
        """Keep the canned text hits."""
        self.hits = hits or []
        self.calls: list[tuple[Any, str, int]] = []

    async def search_text(
        self, owner_id: Any, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Record the call and return the hits."""
        self.calls.append((owner_id, query, limit))
        return list(self.hits)
