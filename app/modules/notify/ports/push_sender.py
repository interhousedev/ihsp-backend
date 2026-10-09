"""Port that delivers one Web Push message."""

from typing import Protocol

from app.modules.notify.domain.push_subscription import PushSubscription


class PushSender(Protocol):
    """Encrypts and posts a payload to a subscription's push service."""

    async def send(self, subscription: PushSubscription, payload: str) -> None:
        """Deliver the JSON text to one device.

        Raises:
            PushGone: the push service no longer knows the subscription.
            PushSendFailed: any other failure; the caller counts it and retries.
        """
        ...
