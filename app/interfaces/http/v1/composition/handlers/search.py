"""GET /v1/me/search."""

from typing import Annotated

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.ports import JsonObject
from app.interfaces.http.v1.composition.services import Composition
from app.shared.actor import Actor

from fastapi import Depends, Query


async def search(
    actor: Annotated[Actor, Depends(get_actor)],
    composition: Annotated[Composition, Depends(get_composition)],
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> JsonObject:
    """Search subjects, lessons, homework, files and flash card sets."""
    return await composition.search_all.execute(actor, q)
