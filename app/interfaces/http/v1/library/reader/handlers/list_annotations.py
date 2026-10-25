"""GET /v1/me/library/annotations?item_id&kind&color&q&cursor."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_reader import AnnotationResponse
from app.modules.library.domain.enums import AnnotationColor, AnnotationKind
from app.modules.library.ports.annotation_repository import AnnotationFilter
from app.shared.pagination import Page

from fastapi import Query


async def list_annotations(
    library: Library,
    actor: SignedIn,
    item_id: UUID | None = None,
    kind: AnnotationKind | None = None,
    color: AnnotationColor | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[AnnotationResponse]:
    """The caller's own annotations, newest first."""
    page = await library.reader.list_annotations.execute(
        actor,
        filters=AnnotationFilter(item_id=item_id, kind=kind, color=color, query=q),
        cursor=cursor,
        limit=limit,
    )
    return Page(
        items=[AnnotationResponse.from_entity(a) for a in page.items],
        next_cursor=page.next_cursor,
    )
