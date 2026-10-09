"""GET /v1/library/items."""

from typing import Annotated

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import ItemsParams
from app.interfaces.http.v1.library.catalogue.schemas_items import ItemCardSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, MaybeSignedIn
from app.modules.library.application.catalogue.list_items import ListItemsQuery
from app.modules.library.domain.enums import UploaderRole
from app.shared.pagination import Page

from fastapi import Query


async def list_items(
    params: Annotated[ItemsParams, Query()],
    library: Library,
    actor: MaybeSignedIn,
    accept_language: AcceptLanguage = None,
) -> Page[ItemCardSchema]:
    """Browse and search; visitors get public items only."""
    page = await library.catalogue.list_items.execute(
        actor,
        ListItemsQuery(
            q=params.q,
            source=params.source,
            subject_id=params.subject_id,
            topic_id=params.topic_id,
            year_of_study=params.year_of_study,
            type=params.type,
            language=params.language,
            collection_id=params.collection_id,
            uploader_role=(
                UploaderRole(params.uploader_role) if params.uploader_role else None
            ),
            has_text=params.has_text,
            shelf=params.shelf,
            sort=params.sort,
            cursor=params.cursor,
            limit=params.limit,
        ),
        accept_language=accept_language,
    )
    return Page[ItemCardSchema](
        items=[ItemCardSchema.from_view(card) for card in page.items],
        next_cursor=page.next_cursor,
    )
