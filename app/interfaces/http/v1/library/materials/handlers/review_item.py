"""POST /v1/manage/library/items/{id}/{action}."""

from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library
from app.interfaces.http.v1.library.materials.locale import locale_for
from app.interfaces.http.v1.library.materials.schemas_moderation import ModerationBody
from app.modules.library.domain.material_flow import ReviewAction

ModerationAction = Literal[
    "approve", "request-changes", "reject", "hold", "restore", "unpublish"
]
ACTIONS = {
    "approve": ReviewAction.APPROVE,
    "request-changes": ReviewAction.REQUEST_CHANGES,
    "reject": ReviewAction.REJECT,
    "hold": ReviewAction.HOLD,
    "restore": ReviewAction.RESTORE,
    "unpublish": ReviewAction.UNPUBLISH,
}


async def review_item(
    item_id: UUID,
    action: ModerationAction,
    library: Library,
    actor: LibrarianActor,
    body: ModerationBody | None = None,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """Decide; a reason is required except for approve, `403 library/own-item`."""
    locale = await locale_for(library, actor, accept_language)
    view = await library.materials.review_item.execute(
        actor,
        item_id,
        ACTIONS[action],
        reason=body.reason if body else None,
        note=body.note if body else None,
        locale=locale,
    )
    return ItemDetailSchema.from_view(view)
