"""A browser's Web Push subscription and the rules for accepting one."""

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.notify.domain.errors import InvalidPushSubscriptionError

MAX_ENDPOINT_LENGTH = 2048
MAX_SUBSCRIPTIONS_PER_USER = 10
"""Devices per user; registering an eleventh drops the oldest."""

MAX_FAILURES = 10
"""Consecutive failed sends after which a subscription is dropped."""

P256DH_BYTES = 65  # uncompressed P-256 point
AUTH_BYTES = 16


@dataclass(slots=True)
class PushSubscription:
    """One browser or installed app that can receive pushes for a user."""

    id: UUID
    user_id: UUID
    endpoint: str
    p256dh: str
    auth: str
    user_agent: str | None
    created_at: datetime
    last_success_at: datetime | None = None
    failures: int = 0


def push_delivery_key(subscription_id: UUID) -> str:
    """Key of a subscription in `Notification.deliveries` (Telegram uses ints)."""
    return f"push:{subscription_id}"


def _decode(value: str, size: int, field: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except ValueError:  # binascii.Error is a ValueError
        raise InvalidPushSubscriptionError(params={"field": field}) from None
    if len(raw) != size:
        raise InvalidPushSubscriptionError(params={"field": field})
    return raw


def _host_allowed(host: str, suffixes: Sequence[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == s or host.endswith(f".{s}") for s in suffixes)


def validate_endpoint(endpoint: str, allowed_suffixes: Sequence[str]) -> None:
    """Accept only https URLs of known push services (the server calls this URL)."""
    try:
        parts = urlsplit(endpoint)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise InvalidPushSubscriptionError(params={"field": "endpoint"}) from None
    ok = (
        len(endpoint) <= MAX_ENDPOINT_LENGTH
        and parts.scheme == "https"
        and host is not None
        and port in (None, 443)
        and not parts.username
        and _host_allowed(host, allowed_suffixes)
    )
    if not ok:
        raise InvalidPushSubscriptionError(params={"field": "endpoint"})


def validate_keys(p256dh: str, auth: str) -> None:
    """Check that the keys decode to a P-256 point and a 16-byte secret."""
    point = _decode(p256dh, P256DH_BYTES, "p256dh")
    if point[0] != 0x04:
        raise InvalidPushSubscriptionError(params={"field": "p256dh"})
    _decode(auth, AUTH_BYTES, "auth")
