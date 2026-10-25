"""POST /v1/library/external/unilibrary/{external_id}/item."""

from typing import Annotated

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemCardSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.external.schemas_external import PinExternalBody

from fastapi import Path, Response, status


async def pin_unilibrary_record(
    external_id: Annotated[str, Path(max_length=40)],
    body: PinExternalBody,
    response: Response,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ItemCardSchema:
    """Store the snapshot of a record; `201` the first time, `200` after that."""
    result = await library.external.pin.execute(
        actor, external_id, category=body.category, accept_language=accept_language
    )
    response.status_code = (
        status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    )
    return ItemCardSchema.from_view(result.card)
