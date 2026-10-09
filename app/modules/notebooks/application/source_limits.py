"""Limits that apply when a source is added (§ 3.2.4)."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.errors import SourceLimitError, SourceTooLargeError
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork
from app.settings import Settings


async def ensure_capacity(
    uow: NotebooksUnitOfWork,
    notebook: Notebook,
    extra_chars: int,
    settings: Settings,
    *,
    pending: int = 0,
) -> None:
    """Raise when one more source of `extra_chars` characters does not fit.

    `pending` counts sources of the same request that are not stored yet.

    Raises:
        SourceLimitError: too many sources, or the notebook text cap is reached.
        SourceTooLargeError: the text alone is over the per-source cap.
    """
    limits = settings.notebooks
    if extra_chars > limits.source_max_chars:
        raise SourceTooLargeError(
            params={"limit": limits.source_max_chars}, support_details="source text"
        )
    count = await uow.sources.count_for_notebook(notebook.id)
    if count + pending >= limits.max_sources:
        raise SourceLimitError(params={"limit": limits.max_sources, "what": "sources"})
    total = await uow.sources.total_chars(notebook.id)
    if total + extra_chars > limits.notebook_max_chars:
        raise SourceLimitError(
            params={"limit": limits.notebook_max_chars, "what": "characters"}
        )
