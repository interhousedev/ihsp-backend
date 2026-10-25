"""Use case: rename a label or change its emoji; an auto label becomes manual."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.label_access import (
    checked_emoji,
    checked_name,
    load_label,
    name_taken,
)
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.label_errors import LabelDuplicateError
from app.modules.notebooks.domain.labels import LabelOrigin, SourceLabel
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

ALLOWED_FIELDS = frozenset({"name", "emoji"})


class UpdateLabel:
    """Applies `name` and `emoji`; once edited, a label is the student's own."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        label_id: UUID,
        changes: Mapping[str, Any],
    ) -> SourceLabel:
        """Apply the changes and return the label.

        An `auto` label that gets any change becomes `manual`, so the next auto run
        keeps it. Fields that are not sent stay as they are.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
            WorkspaceReadOnlyError: A course member who may only read.
            LabelNotFoundError: No such label in the notebook.
            InvalidOptionsError: An unknown or invalid field.
            LabelDuplicateError: Another label has this name.
        """
        unknown = sorted(set(changes) - ALLOWED_FIELDS)
        if unknown:
            raise InvalidOptionsError(params={"field": unknown[0]})
        name = checked_name(changes["name"]) if "name" in changes else None
        emoji = checked_emoji(changes["emoji"]) if "emoji" in changes else None
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, for_update=True)
            label = await load_label(uow, notebook_id, label_id)
            if name is not None and name != label.name:
                others = await uow.labels.list_for_notebook(notebook_id)
                if name_taken(others, name, label.id):
                    raise LabelDuplicateError()
            if name is not None:
                label.name = name
            if emoji is not None:
                label.emoji = emoji
            if changes:
                label.origin = LabelOrigin.MANUAL
                await uow.labels.save(label)
            await uow.commit()
        return label
