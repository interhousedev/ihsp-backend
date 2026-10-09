"""POST /v1/me/library/annotations."""

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_reader import (
    AnnotationInput,
    AnnotationResponse,
)


async def create_annotation(
    body: AnnotationInput, library: Library, actor: SignedIn
) -> AnnotationResponse:
    """Store an annotation; sending the same `client_id` again changes nothing."""
    annotation = await library.reader.create_annotation.execute(actor, body.to_data())
    return AnnotationResponse.from_entity(annotation)
