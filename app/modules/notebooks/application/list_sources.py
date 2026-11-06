"""Use case: the sources of a notebook in the order of the panel (NB-4)."""

from dataclasses import replace
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.sharing import viewable
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


def viewer_source(source: Source) -> Source:
    """A source without what only its owner should see (where it came from, labels)."""
    return replace(source, origin=None, selected=True, label_ids=[], citations=None)


def viewer_sources(sources: list[Source]) -> list[Source]:
    """What a person the notebook is shared with sees of its sources."""
    return [viewer_source(source) for source in viewable(sources)]


class ListSources:
    """Reads all sources of the student's notebook."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, notebook_id: UUID) -> list[Source]:
        """Return the sources ordered by `position`.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, write=False, shared=True
            )
            sources = await uow.sources.list_for_notebook(notebook_id)
        return viewer_sources(sources) if notebook.shared_view else sources
