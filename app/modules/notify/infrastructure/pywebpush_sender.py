"""PushSender over pywebpush: VAPID-signed, aes128gcm-encrypted Web Push."""

from app.modules.notify.domain.push_errors import PushGone, PushSendFailed
from app.modules.notify.domain.push_subscription import PushSubscription
from app.modules.notify.infrastructure.vapid import load_private_key

import aiohttp
import structlog
from pywebpush import WebPushException, webpush_async

log = structlog.get_logger(__name__)

GONE_STATUSES = frozenset({404, 410})
# Every push is a visible, user-facing alert: `high` makes Apple and FCM deliver it at
# once instead of batching it until the device wakes.
URGENCY = "high"


class PywebpushSender:
    """Posts one encrypted message per call through a shared HTTP session."""

    def __init__(
        self,
        *,
        vapid_private_key: str,
        subject: str,
        ttl_seconds: int,
        timeout_seconds: float,
    ) -> None:
        """Load the VAPID key (a bad key fails at startup, not at the first send)."""
        self._vapid = load_private_key(vapid_private_key)
        self._subject = subject
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._session: aiohttp.ClientSession | None = None

    def _http(self) -> aiohttp.ClientSession:
        """The shared session, created inside the running event loop."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def send(self, subscription: PushSubscription, payload: str) -> None:
        """Deliver the payload; 404 and 410 mean the subscription is gone."""
        try:
            await webpush_async(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=payload,
                vapid_private_key=self._vapid,
                vapid_claims={"sub": self._subject},  # the library adds aud and exp
                ttl=self._ttl,
                headers={"Urgency": URGENCY},
                timeout=self._timeout,
                aiohttp_session=self._http(),
            )
        except WebPushException as exc:
            status = exc.status_code
            if status in GONE_STATUSES:
                raise PushGone(f"status {status}") from None
            raise PushSendFailed(f"status {status}: {exc.message[:80]}") from None
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            # ValueError: keys that do not decode; they never will, so the failure
            # counter removes such a subscription after a few tries.
            raise PushSendFailed(type(exc).__name__) from None
