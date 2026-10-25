"""DELETE /v1/me/push-subscriptions: forget a device."""

from collections.abc import Callable

from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.actor import Actor


class RemovePushSubscription:
    """Deletes the caller's subscription with an endpoint; a missing one is fine."""

    def __init__(self, *, uow_factory: Callable[[], NotifyUnitOfWork]) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, endpoint: str) -> None:
        """Delete the row (idempotent: the browser may have lost its subscription)."""
        async with self.uow_factory() as uow:
            await uow.push_subscriptions.delete_by_endpoint(actor.user_id, endpoint)
            await uow.commit()
