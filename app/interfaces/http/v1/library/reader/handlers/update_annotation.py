"""PATCH /v1/me/library/annotations/{annotation_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_reader import (
    AnnotationPatchBody,
    AnnotationResponse,
)
from app.modules.library.domain.reader_annotation import UNCHANGED


async def update_annotation(
    annotation_id: UUID,
    body: AnnotationPatchBody,
    library: Library,
    actor: SignedIn,
) -> AnnotationResponse:
    """Change the note or the colour (`note: null` clears the note)."""
    annotation = await library.reader.update_annotation.execute(
        actor,
        annotation_id,
        note=body.note if "note" in body.model_fields_set else UNCHANGED,
        color=body.color,
    )
    return AnnotationResponse.from_entity(annotation)
