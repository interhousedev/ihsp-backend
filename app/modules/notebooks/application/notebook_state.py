"""Keeping a notebook's counters and summary state in step with its sources."""

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SummaryStatus
from app.modules.notebooks.domain.limits import SUMMARY_DEBOUNCE_SECONDS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork


def selection_hash(sources: Sequence[Source]) -> str:
    """Hash of the texts of the selected usable sources (`summary_hash`).

    It names a set of texts, not of source rows, so every student who holds the same
    files gets the same hash and can share one summary.
    """
    parts = sorted(s.content_hash or "" for s in sources if s.selected and s.usable)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


async def sources_changed(
    uow: NotebooksUnitOfWork, notebook: Notebook, now: datetime
) -> None:
    """Recount sources and characters and make the summary due in 20 seconds.

    Call inside the transaction that added, removed, selected or reprocessed a
    source. The summary is rebuilt only if the selection hash really changed.
    """
    sources = await uow.sources.list_for_notebook(notebook.id)
    notebook.source_count = len(sources)
    notebook.char_count = sum(s.char_count for s in sources if s.usable)
    usable = [s for s in sources if s.selected and s.usable]
    if not usable:
        notebook.summary_status = SummaryStatus.NONE
        notebook.summary_due_at = None
    elif selection_hash(sources) != notebook.summary_hash:
        notebook.summary_status = SummaryStatus.STALE
        notebook.summary_due_at = now + timedelta(seconds=SUMMARY_DEBOUNCE_SECONDS)
    notebook.updated_at = now
    await uow.notebooks.save(notebook)
