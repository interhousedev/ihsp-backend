"""Use case: the Studio list of a notebook (newest first, without content)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class ListArtifacts:
    """Lists the outputs of the student's notebook."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        kind: ArtifactKind | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        """Return the non-deleted outputs; their `content` is None.

        Raises:
            NotebookNotFoundError: Not the student's notebook.
        """
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, write=False)
            return await uow.artifacts.list_for_notebook(
                notebook_id, kind=kind, status=status
            )
