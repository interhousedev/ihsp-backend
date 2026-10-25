"""Port: where vectors are kept, by the hash of their text."""

from collections.abc import Sequence
from typing import Protocol


class EmbeddingStore(Protocol):
    """`vectors.embeddings`; every call is one atomic statement."""

    async def existing(self, content_hashes: Sequence[str], model: str) -> set[str]:
        """The hashes among the given ones that already have a vector of the model."""
        ...

    async def put(
        self, model: str, vectors: Sequence[tuple[str, Sequence[float]]]
    ) -> int:
        """Store `(content_hash, vector)` pairs; a hash that has a vector is kept.

        Returns how many rows were new.
        """
        ...
