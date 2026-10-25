"""Deterministic embeddings for development (`OPENROUTER__MODE=fake`) and tests.

A text becomes a bag of hashed word and word-trigram features, scaled to unit length:
texts that share words or word stems get a high cosine, unrelated texts a low one, and
the same text always gives the same vector. It is no model of meaning, but it makes the
whole pipeline (jobs, storage, hybrid ranking) work without a key.
"""

import hashlib
import math
import re
from collections.abc import Sequence

from app.shared.ai_tasks import EMBEDDING_BATCH_SIZE, EMBEDDING_DIMENSIONS
from app.shared.contracts.embeddings import EmbeddingBatch, EmbedKind

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
FAKE_MODEL = "fake/embedding-v1"
TRIGRAM_WEIGHT = 0.5  # word pieces count half: "fotosintez" ~ "fotosintezda"


def _bucket(feature: str, dims: int) -> tuple[int, float]:
    """Dimension and sign of a feature (stable across processes)."""
    digest = hashlib.sha256(feature.encode()).digest()
    index = int.from_bytes(digest[:4], "big") % dims
    return index, 1.0 if digest[4] % 2 == 0 else -1.0


def fake_vector(text: str, dims: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """The unit vector of a text."""
    values = [0.0] * dims
    for word in _WORD.findall(text.lower()):
        index, sign = _bucket(f"w:{word}", dims)
        values[index] += sign
        padded = f"^{word}$"
        for start in range(max(0, len(padded) - 2)):
            index, sign = _bucket(f"t:{padded[start : start + 3]}", dims)
            values[index] += sign * TRIGRAM_WEIGHT
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return values
    return [v / norm for v in values]


class FakeEmbeddingGateway:
    """The EmbeddingGateway of development and tests; records every call."""

    def __init__(
        self,
        *,
        model: str = FAKE_MODEL,
        dims: int = EMBEDDING_DIMENSIONS,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        """Choose the reported model id, size and batch size."""
        self._model = model
        self._dims = dims
        self._batch_size = batch_size
        self.calls: list[tuple[EmbedKind, list[str]]] = []
        self.error: Exception | None = None  # raised by the next calls when set

    @property
    def model(self) -> str:
        """The fake model id."""
        return self._model

    @property
    def dims(self) -> int:
        """Size of every vector."""
        return self._dims

    @property
    def batch_size(self) -> int:
        """Texts per request."""
        return self._batch_size

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> EmbeddingBatch:
        """Vectors of the texts; 1 token per 4 characters."""
        if self.error is not None:
            raise self.error
        self.calls.append((kind, list(texts)))
        return EmbeddingBatch(
            vectors=[fake_vector(text, self._dims) for text in texts],
            tokens=sum(len(text) // 4 + 1 for text in texts),
            cost_micro=0,
        )

    @property
    def texts(self) -> list[str]:
        """Every text embedded so far, in call order."""
        return [text for _, batch in self.calls for text in batch]
