"""Use case: create an annotation, idempotent by `client_id` (LIB-8, LIB-9)."""

from app.modules.library.application.reader.annotation_data import AnnotationData
from app.modules.library.application.reader.annotation_writer import AnnotationWriter
from app.modules.library.domain.errors import AnnotationNotFoundError
from app.modules.library.domain.reader_annotation import Annotation
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class CreateAnnotation:
    """Add a highlight, note or bookmark to a book or material the actor can read."""

    def __init__(self, *, uow_factory: UowFactory, writer: AnnotationWriter) -> None:
        """Store the unit of work factory and the writer."""
        self.uow_factory = uow_factory
        self.writer = writer

    async def execute(self, actor: Actor, data: AnnotationData) -> Annotation:
        """Create the annotation, or return the one made earlier with this client id."""
        async with self.uow_factory() as uow:
            annotation = await self.writer.upsert(
                uow, actor, data, update_existing=False
            )
            if annotation is None:
                raise AnnotationNotFoundError(
                    support_details=f"client_id {data.client_id} was deleted"
                )
            await uow.commit()
        return annotation
