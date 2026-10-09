"""Choice of the PushSender by `PUSH__ENABLED`."""

from collections.abc import Awaitable, Callable

from app.modules.notify.infrastructure.pywebpush_sender import PywebpushSender
from app.modules.notify.infrastructure.vapid import load_private_key, public_key_of
from app.modules.notify.ports.push_sender import PushSender
from app.settings import PushSettings

Closer = Callable[[], Awaitable[None]]


def make_push_sender(settings: PushSettings) -> tuple[PushSender | None, Closer | None]:
    """Return the real sender and its closer, or (None, None) when push is off.

    Raises:
        ValueError: the private key is unreadable or does not belong to the public
            key (browsers would subscribe with one key and be signed with another).
    """
    if not settings.enabled or settings.vapid_private_key is None:
        return None, None
    private_key = settings.vapid_private_key.get_secret_value()
    if public_key_of(load_private_key(private_key)) != settings.vapid_public_key:
        raise ValueError(
            "PUSH__VAPID_PUBLIC_KEY does not match PUSH__VAPID_PRIVATE_KEY"
        )
    sender = PywebpushSender(
        vapid_private_key=private_key,
        subject=settings.subject,
        ttl_seconds=settings.ttl_seconds,
        timeout_seconds=settings.timeout_seconds,
    )
    return sender, sender.close
