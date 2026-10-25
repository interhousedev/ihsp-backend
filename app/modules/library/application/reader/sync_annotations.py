"""Use case: apply the offline queue of annotations in one go (LIB-9)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.reader.annotation_data import AnnotationData
from app.modules.library.application.reader.annotation_writer import AnnotationWriter
from app.modules.library.domain.reader_annotation import (
    MAX_SYNC_CHANGES,
    Annotation,
    soft_delete,
)
from app.modules.library.domain.reader_errors import SyncTooLargeError
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class SyncAnnotations:
    """Create, update and delete annotations from a device's queue, all or nothing."""

    def __init__(
        self, *, uow_factory: UowFactory, writer: AnnotationWriter, clock: Clock
    ) -> None:
        """Store the unit of work factory, the writer and the clock."""
        self.uow_factory = uow_factory
        self.writer = writer
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        upserts: Sequence[AnnotationData],
        deletes: Sequence[UUID],
    ) -> list[Annotation]:
        """Apply the changes; the result is the live state of the upserted notes.

        `deletes` hold annotation ids or client ids (a device that never synced a
        note knows only the client id). Unknown ids are ignored; deleted notes are
        not part of the result.
        """
        if len(upserts) + len(deletes) > MAX_SYNC_CHANGES:
            raise SyncTooLargeError(params={"max": MAX_SYNC_CHANGES})
        async with self.uow_factory() as uow:
            touched: dict[UUID, Annotation] = {}
            for data in upserts:
                annotation = await self.writer.upsert(
                    uow, actor, data, update_existing=True
                )
                if annotation is not None:
                    touched[annotation.id] = annotation
            now = self.clock.now()
            for found in await uow.annotations.find_any(actor.user_id, list(deletes)):
                if found.deleted_at is None:
                    await uow.annotations.save(soft_delete(found, now=now))
                touched.pop(found.id, None)
            await uow.commit()
        return list(touched.values())
