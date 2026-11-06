"""Files behind the notebooks a user may read: their own and those shared with them."""

from typing import Final
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.sharing import is_shareable
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.contracts.notebooks_files import NotebookFile

MAX_NOTEBOOKS: Final = 500


class VisibleSourceFiles:
    """Own notebooks of every origin (hidden flash card ones too) plus shared ones."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, user_id: UUID) -> list[NotebookFile]:
        """Return the file sources; deleted notebooks are left out."""
        found: list[NotebookFile] = []
        async with self.uow_factory() as uow:
            own = await uow.notebooks.ids_for_owner(user_id)
            shared = await uow.shares.notebooks_of(user_id)
            for notebook_id in own[-MAX_NOTEBOOKS:]:
                notebook = await uow.notebooks.get(notebook_id)
                if notebook is not None and not notebook.is_deleted:
                    found += await _files(uow, notebook, shared=False)
            for notebook_id in shared[:MAX_NOTEBOOKS]:
                notebook = await uow.notebooks.get(notebook_id)
                if notebook is not None and is_shareable(notebook):
                    found += await _files(uow, notebook, shared=True)
        return found


async def _files(
    uow: NotebooksUnitOfWork, notebook: Notebook, *, shared: bool
) -> list[NotebookFile]:
    sources = await uow.sources.list_for_notebook(notebook.id)
    return [
        NotebookFile(
            file_id=UUID(str(source.ref["file_id"])),
            notebook_id=notebook.id,
            origin=notebook.origin.value,
            shared=shared,
        )
        for source in sources
        if source.kind is SourceKind.FILE and source.ref.get("file_id")
    ]
