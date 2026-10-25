"""DELETE /v1/me/push-subscriptions."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.push.schemas import PushUnsubscribeBody
from app.shared.actor import Actor

from fastapi import Depends, Response


async def unsubscribe(
    body: PushUnsubscribeBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> Response:
    """Forget the caller's subscription with this endpoint."""
    await container.notify.remove_push_subscription.execute(actor, body.endpoint)
    return Response(status_code=204)
