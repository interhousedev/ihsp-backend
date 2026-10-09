"""Copying the topic labels of a notebook together with its sources."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from app.modules.notebooks.domain.labels import LabelLink, SourceLabel
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork
from app.shared.ids import new_id


async def copy_labels(
    uow: NotebooksUnitOfWork,
    original_id: UUID,
    copy_id: UUID,
    source_ids: Mapping[UUID, UUID],
    now: datetime,
) -> None:
    """Give the copy the labels of the original and their links.

    Args:
        uow: The open unit of work (the copy and its sources are already added).
        original_id: The notebook that is copied.
        copy_id: The new notebook.
        source_ids: Source id in the original -> source id in the copy.
        now: Creation time of the copied labels.
    """
    label_ids: dict[UUID, UUID] = {}
    for label in await uow.labels.list_for_notebook(original_id):
        clone = SourceLabel(
            id=new_id(),
            notebook_id=copy_id,
            name=label.name,
            emoji=label.emoji,
            position=label.position,
            origin=label.origin,
            created_at=now,
        )
        await uow.labels.add(clone)
        label_ids[label.id] = clone.id
    links = await uow.labels.links_for_notebook(original_id)
    await uow.labels.add_links(
        [
            LabelLink(source_ids[link.source_id], label_ids[link.label_id], link.origin)
            for link in links
            if link.source_id in source_ids and link.label_id in label_ids
        ]
    )
