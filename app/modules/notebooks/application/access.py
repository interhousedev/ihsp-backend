"""Loading a notebook, source or output the caller may use (anything else is a 404).

A personal notebook is its owner's alone. The workspace of an LMS course is shared
by the course staff: ``edit`` reads and writes it, ``view_drafts`` only reads it, and
everyone else gets the same 404 as for a missing notebook. A use case that is safe for
a person the owner shared the notebook with passes ``shared=True``; every other use
case keeps answering them with a 404, so a new use case is closed by default.
Every row of a notebook
(sources, outputs) carries the notebook's ``owner_id``, so rows are checked against
the notebook, never against the caller.
"""

from uuid import UUID

from app.modules.notebooks.domain.entities import Artifact, Notebook, Source
from app.modules.notebooks.domain.errors import (
    NotebookNotFoundError,
    WorkspaceReadOnlyError,
)
from app.modules.notebooks.domain.sharing import VIEWABLE_KINDS, is_shareable
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork


async def _check_workspace(
    uow: NotebooksUnitOfWork, user_id: UUID, notebook: Notebook, *, write: bool
) -> None:
    """Let a course member in (read or write) and note whether they may write."""
    if notebook.course_id is None:
        raise NotebookNotFoundError()
    access = await uow.course_gate.access(user_id, notebook.course_id)
    if access is None or not access.can_read:
        raise NotebookNotFoundError()
    if write and not access.can_write:
        raise WorkspaceReadOnlyError()
    notebook.can_write = access.can_write


async def _check_share(
    uow: NotebooksUnitOfWork, user_id: UUID, notebook: Notebook
) -> None:
    """Let in a person with a live grant, read-only; everyone else gets a 404."""
    if (
        not is_shareable(notebook)
        or await uow.shares.active(notebook.id, user_id) is None
    ):
        raise NotebookNotFoundError()
    notebook.can_write = False
    notebook.shared_view = True


async def load_notebook(
    uow: NotebooksUnitOfWork,
    user_id: UUID,
    notebook_id: UUID,
    *,
    for_update: bool = False,
    include_deleted: bool = False,
    write: bool = True,
    shared: bool = False,
) -> Notebook:
    """Return a notebook the user may use or raise `NotebookNotFoundError`.

    ``write=False`` is for reading (and for the reader's own data: their chat thread,
    their progress); a course member who may only read gets
    `WorkspaceReadOnlyError` for anything else. ``shared=True`` (reading only) also
    admits a person the owner shared the notebook with, marked ``shared_view``.
    """
    notebooks = uow.notebooks
    found = await (
        notebooks.get_for_update(notebook_id)
        if for_update
        else notebooks.get(notebook_id)
    )
    if found is None or (found.is_deleted and not include_deleted):
        raise NotebookNotFoundError()
    if found.is_course_workspace:
        await _check_workspace(uow, user_id, found, write=write)
    elif found.owner_id != user_id:
        if not shared or write:
            raise NotebookNotFoundError()
        await _check_share(uow, user_id, found)
    return found


async def load_source(
    uow: NotebooksUnitOfWork,
    user_id: UUID,
    notebook_id: UUID,
    source_id: UUID,
    *,
    for_update: bool = False,
    write: bool = True,
    shared: bool = False,
) -> Source:
    """Return a source of a notebook the user may use or raise a 404."""
    notebook = await load_notebook(
        uow, user_id, notebook_id, write=write, shared=shared
    )
    sources = uow.sources
    found = await (
        sources.get_for_update(source_id) if for_update else sources.get(source_id)
    )
    if (
        found is None
        or found.notebook_id != notebook_id
        or found.owner_id != notebook.owner_id
        or (notebook.shared_view and found.kind not in VIEWABLE_KINDS)
    ):
        raise NotebookNotFoundError()
    return found


async def load_artifact(
    uow: NotebooksUnitOfWork,
    user_id: UUID,
    notebook_id: UUID,
    artifact_id: UUID,
    *,
    for_update: bool = False,
    write: bool = True,
) -> Artifact:
    """Return an output of a notebook the user may use or raise a 404."""
    notebook = await load_notebook(uow, user_id, notebook_id, write=write)
    artifacts = uow.artifacts
    found = await (
        artifacts.get_for_update(artifact_id)
        if for_update
        else artifacts.get(artifact_id)
    )
    if (
        found is None
        or found.deleted_at is not None
        or found.notebook_id != notebook_id
        or found.owner_id != notebook.owner_id
    ):
        raise NotebookNotFoundError()
    return found
