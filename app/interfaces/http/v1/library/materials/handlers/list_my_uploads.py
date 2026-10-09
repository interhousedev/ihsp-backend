"""GET /v1/me/library/uploads."""

from typing import Annotated

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.materials.locale import locale_for
from app.interfaces.http.v1.library.materials.schemas_materials import (
    UploadRowResponse,
    UploadsParams,
)
from app.shared.pagination import Page

from fastapi import Query


async def list_my_uploads(
    params: Annotated[UploadsParams, Query()],
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> Page[UploadRowResponse]:
    """My materials with status, reason and place in the review queue."""
    locale = await locale_for(library, actor, accept_language)
    page = await library.materials.list_my_uploads.execute(
        actor,
        status=params.status,
        cursor=params.cursor,
        limit=params.limit,
        locale=locale,
    )
    return Page[UploadRowResponse](
        items=[UploadRowResponse.from_view(row) for row in page.items],
        next_cursor=page.next_cursor,
    )
