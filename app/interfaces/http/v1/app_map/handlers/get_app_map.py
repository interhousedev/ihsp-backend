"""GET /v1/app-map."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.app_map.schemas import AppMapItem, AppMapResponse
from app.shared.actor import Actor
from app.shared.app_map import for_roles, hidden_pages

from fastapi import Depends


async def get_app_map(
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> AppMapResponse:
    """List the pages of every app that the caller's roles may open."""
    found = for_roles(
        container.settings.urls,
        actor.roles,
        hidden_pages(container.settings.features),
    )
    return AppMapResponse(
        items=[
            AppMapItem(
                id=f.destination.id,
                app=f.destination.app,
                path=f.destination.path,
                url=f.url,
                title=f.destination.title,
                keywords=list(f.destination.keywords),
            )
            for f in found
        ]
    )
