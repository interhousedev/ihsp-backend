"""Creates or updates one annotation by `client_id`; shared by create and sync."""

from app.modules.library.application.reader.access import (
    load_readable_item,
    require_file,
)
from app.modules.library.application.reader.annotation_data import AnnotationData
from app.modules.library.domain.reader_annotation import (
    Annotation,
    build_annotation,
    edit_annotation,
)
from app.modules.library.domain.reader_locator import validate_locator
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock


class AnnotationWriter:
    """Idempotent writes of annotations inside an open unit of work."""

    def __init__(self, *, clock: Clock) -> None:
        """Store the clock."""
        self.clock = clock

    async def upsert(
        self,
        uow: LibraryUnitOfWork,
        actor: Actor,
        data: AnnotationData,
        *,
        update_existing: bool,
    ) -> Annotation | None:
        """The annotation for `data.client_id`, created when it does not exist.

        An existing live annotation is returned as it is, or with the note and the
        colour of `data` when `update_existing` (an offline edit). None means the
        client id belongs to a deleted annotation, which stays deleted.
        """
        existing = await uow.annotations.get_by_client_id(actor.user_id, data.client_id)
        if existing is not None:
            return await self._existing(uow, existing, data, update_existing)
        item = await load_readable_item(uow, actor, data.item_id)
        item_file = require_file(item, data.file_id)
        annotation = build_annotation(
            user_id=actor.user_id,
            item_id=item.id,
            file_id=data.file_id,
            kind=data.kind,
            locator=validate_locator(data.locator, item_file.format),
            quote=data.quote,
            note=data.note,
            color=data.color,
            client_id=data.client_id,
            now=self.clock.now(),
        )
        if await uow.annotations.add(annotation):
            return annotation
        # Another request with the same client id won the race: use its row.
        winner = await uow.annotations.get_by_client_id(actor.user_id, data.client_id)
        return None if winner is None or winner.deleted_at else winner

    async def _existing(
        self,
        uow: LibraryUnitOfWork,
        existing: Annotation,
        data: AnnotationData,
        update_existing: bool,
    ) -> Annotation | None:
        if existing.deleted_at is not None:
            return None
        if not update_existing:
            return existing
        edited = edit_annotation(
            existing, now=self.clock.now(), note=data.note, color=data.color
        )
        if edited is not existing:
            await uow.annotations.save(edited)
        return edited
