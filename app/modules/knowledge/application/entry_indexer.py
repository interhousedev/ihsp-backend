"""Gives an entry its vector (best effort: search by words works without it)."""

from collections.abc import Callable

from app.modules.knowledge.domain.entry import KnowledgeEntry, embed_text
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.embeddings import EmbeddingIndex, TextToEmbed

import structlog

log = structlog.get_logger(__name__)

EmbeddingsProvider = Callable[[], EmbeddingIndex | None]
"""Late-bound: the index is built after the module (None: search by meaning is off)."""


class EntryIndexer:
    """Embeds `key + title + value` of an entry; equal texts share one vector."""

    def __init__(self, *, embeddings: EmbeddingsProvider) -> None:
        """Store the provider of the embedding index."""
        self._embeddings = embeddings

    async def index(self, entry: KnowledgeEntry) -> None:
        """Make sure the entry's current text has a vector; never raises."""
        index = self._embeddings()
        if index is None or entry.content_hash is None:
            return
        try:
            await index.ensure([TextToEmbed(entry.content_hash, embed_text(entry))])
        except AiProviderError as error:
            log.warning("knowledge_embed_failed", key=entry.key, error=repr(error))
