"""In-memory fakes of the vectors module's ports."""

from collections.abc import Sequence


class FakeEmbeddingStore:
    """Vectors by (model, content hash), in a dict."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[tuple[str, str], list[float]] = {}
        self.put_calls: list[int] = []  # size of each put

    async def existing(self, content_hashes: Sequence[str], model: str) -> set[str]:
        """The hashes that have a vector of the model."""
        return {h for h in content_hashes if (model, h) in self.rows}

    async def put(
        self, model: str, vectors: Sequence[tuple[str, Sequence[float]]]
    ) -> int:
        """Store new rows only."""
        self.put_calls.append(len(vectors))
        added = 0
        for content_hash, values in vectors:
            if (model, content_hash) not in self.rows:
                self.rows[(model, content_hash)] = list(values)
                added += 1
        return added


class FakeTokenBudget:
    """A daily budget that starts with `limit` tokens (None: unlimited)."""

    def __init__(self, limit: int | None = None) -> None:
        """Set the limit."""
        self.limit = limit
        self.spent = 0

    async def remaining(self) -> int | None:
        """Tokens left."""
        return None if self.limit is None else max(0, self.limit - self.spent)

    async def spend(self, tokens: int) -> None:
        """Count the tokens."""
        self.spent += tokens


class FakeQueryCache:
    """Question vectors in a dict; remembers the ttl it was given."""

    def __init__(self) -> None:
        """Start empty."""
        self.values: dict[str, list[float]] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key: str) -> list[float] | None:
        """The cached vector."""
        return self.values.get(key)

    async def put(self, key: str, values: Sequence[float], ttl_seconds: int) -> None:
        """Remember a vector."""
        self.values[key] = list(values)
        self.ttl[key] = ttl_seconds
