"""Dropping the text of a source whose file is gone (FILE-6, NB-3)."""

from datetime import datetime

from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import GuideStatus, SourceFailure, SourceStatus
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork


async def mark_unavailable(
    uow: NotebooksUnitOfWork,
    source: Source,
    now: datetime,
    failure: SourceFailure = SourceFailure.DELETED,
) -> None:
    """Mark the source `unavailable (<failure>, deleted by default)`, drop its text.

    The row stays with its title; the link to the text, the guide and the counters go
    with the file's text. The shared document stays for other notebooks that hold it
    (the purge job deletes it when nobody does). The caller refreshes the notebook
    counters (`sources_changed`). A library source whose item was held gets
    `forbidden`; a later sync reads it again.
    """
    source.document_id = None
    source.status = SourceStatus.UNAVAILABLE
    source.failure = failure
    source.content_hash = None
    source.upstream_version = None
    source.word_count = 0
    source.char_count = 0
    source.token_estimate = 0
    source.passage_count = 0
    source.guide = None
    source.guide_status = GuideStatus.NONE
    source.updated_at = now
    await uow.sources.save(source)
