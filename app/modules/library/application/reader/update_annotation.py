"""Use case: change the note or the colour of an annotation (LIB-8)."""

from uuid import UUID

from app.modules.library.domain.enums import AnnotationColor
from app.modules.library.domain.errors import AnnotationNotFoundError
from app.modules.library.domain.reader_annotation import (
    UNCHANGED,
    Annotation,
    Unchanged,
    edit_annotation,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class UpdateAnnotation:
    """Edit one of the actor's own annotations."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        annotation_id: UUID,
        *,
        note: str | None | Unchanged = UNCHANGED,
        color: AnnotationColor | None = None,
    ) -> Annotation:
        """Apply the new note (None clears it) and/or colour; 404 for others' notes."""
        async with self.uow_factory() as uow:
            current = await uow.annotations.get(actor.user_id, annotation_id)
            if current is None:
                raise AnnotationNotFoundError(support_details=f"{annotation_id}")
            edited = edit_annotation(current, now=self.clock.now(), note=note, color=color)
            if edited is not current:
                await uow.annotations.save(edited)
                await uow.commit()
        return edited
