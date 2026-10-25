"""Job `notebooks.embed_passages`: vectors for passages that have none (NB-14)."""

from uuid import UUID

from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.contracts.embeddings import EmbeddingIndex
from app.shared.features import Feature, is_enabled

import structlog

log = structlog.get_logger(__name__)

DOCUMENT_ROUNDS = 20  # a document of 600 000 characters has about 700 passages


class EmbedPassages:
    """Embeds each distinct passage text once, whoever holds it.

    Passages are identified by the sha256 of their text (`content_hash`), so a lesson
    file read by 30 students, or a text pasted twice, is sent to the model once. With a
    `document_id` (kicked after `process_source` stored a new document) the job
    embeds that document's missing texts; without one (the cron backfill) it takes
    the next `VECTORS__BACKFILL_TEXTS_PER_RUN` texts of any document. The daily token
    budget of the vectors module caps both.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        embeddings: EmbeddingIndex | None,
        settings: Settings,
    ) -> None:
        """Store the collaborators; `embeddings` None means search by meaning is off."""
        self.uow_factory = uow_factory
        self.embeddings = embeddings
        self.settings = settings

    async def execute(self, document_id: UUID | None = None) -> dict[str, int]:
        """Embed missing passage texts; returns what was done.

        Raises:
            AiProviderError: The provider failed; the task is retried and the cron
                run picks up whatever is still missing.
        """
        totals = {"embedded": 0, "deferred": 0, "tokens": 0, "cost_micro": 0}
        index = self.embeddings
        if index is None or not is_enabled(self.settings, Feature.VECTOR_SEARCH):
            return totals
        size = self.settings.vectors.backfill_texts_per_run
        for _ in range(1 if document_id is None else DOCUMENT_ROUNDS):
            async with self.uow_factory() as uow:
                texts = await uow.passages.missing_embeddings(
                    index.model, size, document_id=document_id
                )
            if not texts:
                break
            report = await index.ensure(texts)
            totals["embedded"] += report.embedded
            totals["tokens"] += report.tokens
            totals["cost_micro"] += report.cost_micro
            totals["deferred"] = report.deferred
            if report.deferred or not report.embedded:
                break  # budget spent (or nothing could be stored): try again later
        log.info("notebooks_passages_embedded", **totals)
        return totals
