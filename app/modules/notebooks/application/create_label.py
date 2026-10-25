"""Use case: make a label by hand (G12)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.label_access import (
    checked_emoji,
    checked_name,
    name_taken,
)
from app.modules.notebooks.domain.label_errors import (
    LabelDuplicateError,
    LabelsLimitError,
)
from app.modules.notebooks.domain.labels import (
    MAX_LABELS,
    MAX_LABELS_PER_SOURCE,
    LabelOrigin,
    SourceLabel,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateLabel:
    """Adds a `manual` label to a notebook."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, actor: Actor, notebook_id: UUID, name: str, emoji: str
    ) -> SourceLabel:
        """Store the label after the others and return it.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
            WorkspaceReadOnlyError: A course member who may only read.
            InvalidOptionsError: An empty or too long name, or a too long emoji.
            LabelsLimitError: The notebook already has 12 labels.
            LabelDuplicateError: A label with this name exists.
        """
        checked = (checked_name(name), checked_emoji(emoji))
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, for_update=True)
            labels = await uow.labels.list_for_notebook(notebook_id)
            if len(labels) >= MAX_LABELS:
                raise LabelsLimitError(
                    params={"limit": MAX_LABELS, "per_source": MAX_LABELS_PER_SOURCE}
                )
            if name_taken(labels, checked[0], None):
                raise LabelDuplicateError()
            label = SourceLabel(
                id=new_id(),
                notebook_id=notebook_id,
                name=checked[0],
                emoji=checked[1],
                position=max((item.position for item in labels), default=0) + 1,
                origin=LabelOrigin.MANUAL,
                created_at=self.clock.now(),
            )
            await uow.labels.add(label)
            await uow.commit()
        return label
