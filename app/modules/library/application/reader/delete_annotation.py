"""Use case: delete an annotation (LIB-8)."""

from uuid import UUID

from app.modules.library.domain.errors import AnnotationNotFoundError
from app.modules.library.domain.reader_annotation import soft_delete
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class DeleteAnnotation:
    """Soft-delete one of the actor's own annotations."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor, annotation_id: UUID) -> None:
        """Mark the annotation deleted; 404 when it is missing or not the actor's."""
        async with self.uow_factory() as uow:
            current = await uow.annotations.get(actor.user_id, annotation_id)
            if current is None:
                raise AnnotationNotFoundError(support_details=f"{annotation_id}")
            await uow.annotations.save(soft_delete(current, now=self.clock.now()))
            await uow.commit()
