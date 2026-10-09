"""GET /v1/push/config."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.push.schemas import PushConfigResponse
from app.shared.actor import Actor

from fastapi import Depends


async def get_config(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> PushConfigResponse:
    """Say whether Web Push is on and give the public VAPID key."""
    config = container.notify.push_config.execute()
    return PushConfigResponse(
        enabled=config.enabled, vapid_public_key=config.vapid_public_key
    )
