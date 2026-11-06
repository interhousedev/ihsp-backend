"""Use case: one passage with its neighbours (citation popover and viewer, NB-7)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.linked_sets import readable_linked
from app.modules.notebooks.application.views import PassageDetailView
from app.modules.notebooks.domain.entities import Notebook, Passage
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.domain.sharing import VIEWABLE_KINDS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.actor import Actor

CONTEXT_MAX = 5


async def _find(
    uow: NotebooksUnitOfWork, actor: Actor, notebook: Notebook, passage_id: UUID
) -> tuple[Passage, Notebook]:
    """The passage in the notebook or, for its owner, in a set attached to it."""
    passage = await uow.passages.get(passage_id, notebook.id)
    if passage is not None:
        return passage, notebook
    if notebook.owner_id == actor.user_id:
        for linked in await uow.shares.linked_sets(notebook.id):
            home = await readable_linked(uow, actor.user_id, linked.linked_notebook_id)
            if home is None:
                continue
            passage = await uow.passages.get(passage_id, home.id)
            if passage is not None:
                return passage, home
    raise NotebookNotFoundError()


class GetPassage:
    """Reads a passage of the student's notebook; any other passage is a 404."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, actor: Actor, notebook_id: UUID, passage_id: UUID, context: int = 0
    ) -> PassageDetailView:
        """Return the passage, its source and `context` (0 to 5) passages each side.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's, or the passage
                or its source does not belong to it.
        """
        around = min(max(context, 0), CONTEXT_MAX)
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, write=False, shared=True
            )
            passage, home = await _find(uow, actor, notebook, passage_id)
            source = await uow.sources.get(passage.source_id)
            if (
                source is None
                or source.notebook_id != home.id
                or (
                    home.owner_id != actor.user_id and source.kind not in VIEWABLE_KINDS
                )
            ):
                raise NotebookNotFoundError()
            before, after = await uow.passages.neighbours(
                passage.source_id, passage.seq, around
            )
        return PassageDetailView(
            passage=passage, source=source, before=before, after=after
        )
