"""POST /v1/me/push-subscriptions."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.push.schemas import (
    PushSubscriptionBody,
    PushSubscriptionResponse,
)
from app.shared.actor import Actor

from fastapi import Depends


async def subscribe(
    body: PushSubscriptionBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> PushSubscriptionResponse:
    """Save this browser for the caller (an endpoint seen before changes owner)."""
    subscription_id = await container.notify.register_push_subscription.execute(
        actor,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=body.user_agent,
    )
    return PushSubscriptionResponse(id=subscription_id)
