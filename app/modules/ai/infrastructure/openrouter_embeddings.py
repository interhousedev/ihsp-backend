"""OpenRouter adapter of the EmbeddingGateway (`POST /embeddings`)."""

from collections.abc import Sequence
from typing import Any

from app.modules.ai.domain.errors import AiProviderError
from app.modules.ai.infrastructure.openrouter import MICRO, OpenRouterGateway
from app.shared.ai_tasks import ModelProfile
from app.shared.contracts.embeddings import EmbeddingBatch, EmbedKind

REQUEST_TIMEOUT_SECONDS = 60.0


def parse_embeddings(data: dict[str, Any], *, count: int, dims: int) -> EmbeddingBatch:
    """The vectors, tokens and cost of an embeddings response.

    Raises:
        AiProviderError: The answer has another number of vectors than texts, or a
            vector of another size (a model that ignores `dimensions`).
    """
    items = sorted(data.get("data") or [], key=lambda item: int(item.get("index", 0)))
    vectors = [[float(x) for x in item.get("embedding") or []] for item in items]
    if len(vectors) != count:
        raise AiProviderError(
            support_details=f"embeddings: {len(vectors)} vectors for {count} texts"
        )
    sizes = {len(vector) for vector in vectors}
    if sizes != {dims} and count:
        raise AiProviderError(
            support_details=f"embeddings: vector size {sorted(sizes)}, expected {dims}"
        )
    usage = data.get("usage") or {}
    cost = usage.get("cost")
    return EmbeddingBatch(
        vectors=vectors,
        tokens=int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0),
        cost_micro=None if cost is None else round(float(cost) * MICRO),
    )


class OpenRouterEmbeddings:
    """Embeds with the model of the `EMBEDDING` AI task profile.

    `queries` and `documents` get the profile's prefixes (Qwen3 wants a task line
    before a question, e5 wants `query: ` and `passage: `). `dimensions` is always
    sent, so a model with Matryoshka training returns exactly the stored size.
    """

    def __init__(self, gateway: OpenRouterGateway, profile: ModelProfile) -> None:
        """Keep the connection and the profile."""
        self._gateway = gateway
        self._profile = profile

    @property
    def model(self) -> str:
        """The OpenRouter model id."""
        return self._profile.model

    @property
    def dims(self) -> int:
        """Size of every vector."""
        return self._profile.dimensions

    @property
    def batch_size(self) -> int:
        """Texts per request."""
        return self._profile.batch_size

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> EmbeddingBatch:
        """Vectors of the texts, in order."""
        if not texts:
            return EmbeddingBatch(vectors=[], tokens=0)
        profile = self._profile
        prefix = profile.query_prefix if kind == "query" else profile.document_prefix
        body: dict[str, Any] = {
            "model": profile.model,
            "input": [f"{prefix}{text}" for text in texts],
            "encoding_format": "float",
            "dimensions": profile.dimensions,
        }
        provider = profile.provider()
        if provider is not None:
            body["provider"] = provider
        data = await self._gateway.embeddings(
            body, timeout_seconds=REQUEST_TIMEOUT_SECONDS
        )
        return parse_embeddings(data, count=len(texts), dims=profile.dimensions)
