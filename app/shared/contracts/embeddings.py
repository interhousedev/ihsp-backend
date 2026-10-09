"""Embedding contracts: the gateway to a model, and the index other modules call.

`EmbeddingGateway` (provider: ai module, OpenRouter or a fake) turns texts into
vectors. `EmbeddingIndex` (provider: vectors module) is what a module that wants
search by meaning uses: it embeds each distinct text once, remembers the vector by the
sha256 of the text and answers "the vector of this question".
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

EmbedKind = Literal["query", "document"]
"""A question or a passage: some models prepare the two differently."""


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    """The result of one embedding request."""

    vectors: list[list[float]]  # in the order of the texts
    tokens: int  # tokens the provider billed
    cost_micro: int | None = None  # millionths of a US dollar, when the provider says


@dataclass(frozen=True, slots=True)
class QueryVector:
    """The vector of a question and the model that made it.

    Passage vectors of another model live in another space, so a search matches the
    model name before it compares a single number.
    """

    model: str
    values: Sequence[float]


@dataclass(frozen=True, slots=True)
class TextToEmbed:
    """A text and its identity (sha256 of the text, 64 hex characters)."""

    content_hash: str
    text: str


@dataclass(frozen=True, slots=True)
class EmbedReport:
    """What one `ensure` call did."""

    embedded: int = 0  # texts sent to the model and stored
    already: int = 0  # texts that had a vector (nothing was paid)
    deferred: int = 0  # texts left for later (daily token budget reached)
    tokens: int = 0
    cost_micro: int = 0


class EmbeddingGateway(Protocol):
    """Text to vector (OpenRouter in production, a deterministic fake in tests)."""

    @property
    def model(self) -> str:
        """The model id that made the vectors (the key next to `content_hash`)."""
        ...

    @property
    def dims(self) -> int:
        """Size of every vector."""
        ...

    @property
    def batch_size(self) -> int:
        """Texts one request may carry."""
        ...

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> EmbeddingBatch:
        """Vectors of the texts in the same order.

        Raises:
            AiProviderError: The provider failed or answered with the wrong shape.
        """
        ...


class EmbeddingIndex(Protocol):
    """Public API of the vectors module."""

    @property
    def model(self) -> str:
        """The model id of the vectors it stores and searches."""
        ...

    async def ensure(self, texts: Sequence[TextToEmbed]) -> EmbedReport:
        """Give every distinct text a vector; texts that have one cost nothing.

        Stops early when the daily token budget is spent (`deferred` says how many
        were left). Raises `AiProviderError` when the provider fails; what was stored
        before the failure stays.
        """
        ...

    async def embed_query(self, text: str) -> QueryVector | None:
        """The vector of a question, cached by its text.

        None when the question is empty, the provider is slow (more than
        `VECTORS__QUERY_TIMEOUT_SECONDS`) or fails: the caller then searches by words.
        """
        ...
