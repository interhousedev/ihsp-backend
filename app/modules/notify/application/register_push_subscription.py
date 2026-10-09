"""POST /v1/me/push-subscriptions: remember a device for Web Push."""

from collections.abc import Callable, Sequence
from uuid import UUID

from app.modules.notify.domain.push_subscription import (
    MAX_SUBSCRIPTIONS_PER_USER,
    validate_endpoint,
    validate_keys,
)
from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock

MAX_USER_AGENT_CHARS = 512


class RegisterPushSubscription:
    """Saves a browser subscription for the caller; the same endpoint moves to them."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], NotifyUnitOfWork],
        clock: Clock,
        allowed_suffixes: Sequence[str],
    ) -> None:
        """Store the ports and the push services whose endpoints are accepted."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.allowed_suffixes = tuple(allowed_suffixes)

    async def execute(
        self,
        actor: Actor,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None = None,
    ) -> UUID:
        """Validate and upsert by endpoint; keep only the caller's newest devices.

        A browser that was used by someone else before keeps the same endpoint, so
        the row changes owner instead of sending the old user's messages to it.
        """
        validate_endpoint(endpoint, self.allowed_suffixes)
        validate_keys(p256dh, auth)
        agent = user_agent[:MAX_USER_AGENT_CHARS] if user_agent else None
        async with self.uow_factory() as uow:
            subscription_id = await uow.push_subscriptions.upsert(
                user_id=actor.user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=agent,
                now=self.clock.now(),
            )
            await uow.push_subscriptions.trim(actor.user_id, MAX_SUBSCRIPTIONS_PER_USER)
            await uow.commit()
        return subscription_id
