"""Use case: set the labels of one source by hand (G12)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.domain.label_errors import (
    LabelNotFoundError,
    LabelsLimitError,
)
from app.modules.notebooks.domain.labels import (
    MAX_LABELS,
    MAX_LABELS_PER_SOURCE,
    LabelOrigin,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class SetSourceLabels:
    """Replaces the labels of a source; the links become `manual`."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        source_id: UUID,
        label_ids: list[UUID],
    ) -> Source:
        """Make exactly `label_ids` (repeats dropped, order kept) the source's labels.

        A link set here is never replaced by an auto run. Returns the source.

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's.
            WorkspaceReadOnlyError: A course member who may only read.
            LabelsLimitError: More than 3 labels.
            LabelNotFoundError: A label of another notebook or a missing one.
        """
        ids = list(dict.fromkeys(label_ids))
        if len(ids) > MAX_LABELS_PER_SOURCE:
            raise LabelsLimitError(
                params={"limit": MAX_LABELS, "per_source": MAX_LABELS_PER_SOURCE}
            )
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, for_update=True)
            await load_source(uow, actor.user_id, notebook_id, source_id)
            known = {label.id for label in await uow.labels.list_for_notebook(notebook_id)}
            if not set(ids) <= known:
                raise LabelNotFoundError()
            await uow.labels.replace_links(source_id, ids, LabelOrigin.MANUAL)
            await uow.commit()
            found = await uow.sources.get(source_id)
        if found is None:  # pragma: no cover - the source was just loaded
            raise NotebookNotFoundError()
        return found
