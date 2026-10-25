"""Creating `note` sources: from the editor, a chat answer or a report (§ 3.4.10)."""

from datetime import datetime
from uuid import UUID

from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.source_limits import ensure_capacity
from app.modules.notebooks.domain.entities import Citation, Notebook, Source
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.limits import SOURCE_TITLE_MAX_CHARS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork
from app.settings import Settings
from app.shared.ids import new_id

NOTE_TITLE_FROM_TEXT = 60


def note_title(title: str | None, body: str, fallback: str) -> str:
    """The given title, else the first words of the text, else `fallback`."""
    flat = " ".join((title or "").split())
    if not flat:
        flat = " ".join(body.split())[:NOTE_TITLE_FROM_TEXT]
    return (flat or fallback)[:SOURCE_TITLE_MAX_CHARS]


async def create_note_source(
    uow: NotebooksUnitOfWork,
    notebook: Notebook,
    *,
    owner_id: UUID,
    title: str,
    body_md: str,
    citations: list[Citation] | None,
    now: datetime,
    settings: Settings,
) -> Source:
    """Add a pending `note` source inside the open transaction.

    The caller commits and kicks `notebooks.process_source` for the returned source
    (`uow.after_commit`). The notebook counters are refreshed here.

    Raises:
        SourceLimitError: the notebook is full.
        SourceTooLargeError: the note is longer than the per-source cap.
    """
    await ensure_capacity(uow, notebook, len(body_md), settings)
    source = Source(
        id=new_id(),
        notebook_id=notebook.id,
        owner_id=owner_id,
        kind=SourceKind.NOTE,
        title=title[:SOURCE_TITLE_MAX_CHARS],
        position=await uow.sources.next_position(notebook.id),
        created_at=now,
        updated_at=now,
        body_md=body_md,
        citations=citations or None,
        selected=True,
        status=SourceStatus.PENDING,
    )
    await uow.sources.add(source)
    await sources_changed(uow, notebook, now)
    return source
