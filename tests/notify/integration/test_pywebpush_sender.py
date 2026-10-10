"""The real Web Push sender against a local fake push service (no external network)."""

import base64
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.notify.domain.push_errors import PushGone, PushSendFailed
from app.modules.notify.domain.push_subscription import PushSubscription
from app.modules.notify.infrastructure.pywebpush_sender import PywebpushSender
from app.modules.notify.infrastructure.vapid import VapidKeys, generate_vapid_keys

import http_ece
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class PushService:
    """A browser's key pair and the requests its fake push service received."""

    server: TestServer
    private_key: ec.EllipticCurvePrivateKey
    auth_secret: bytes
    requests: list[dict[str, str]] = field(default_factory=list)
    plaintexts: list[str] = field(default_factory=list)

    def subscription(self, status: int = 201) -> PushSubscription:
        public = self.private_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return PushSubscription(
            id=uuid4(),
            user_id=uuid4(),
            endpoint=str(self.server.make_url(f"/push?status={status}")),
            p256dh=_b64(public),
            auth=_b64(self.auth_secret),
            user_agent=None,
            created_at=datetime.now(UTC),
        )


@pytest_asyncio.fixture
async def push_service() -> AsyncIterator[PushService]:
    key = ec.generate_private_key(ec.SECP256R1())
    secret = os.urandom(16)
    holder: dict[str, PushService] = {}

    async def receive(request: web.Request) -> web.Response:
        service = holder["service"]
        service.requests.append(dict(request.headers))
        body = await request.read()
        plain = http_ece.decrypt(
            body, private_key=key, auth_secret=secret, version="aes128gcm"
        )
        service.plaintexts.append(plain.decode())
        return web.Response(status=int(request.query["status"]))

    app = web.Application()
    app.router.add_post("/push", receive)
    server = TestServer(app)
    await server.start_server()
    holder["service"] = PushService(server=server, private_key=key, auth_secret=secret)
    try:
        yield holder["service"]
    finally:
        await server.close()


@pytest.fixture
def keys() -> VapidKeys:
    return generate_vapid_keys()


@pytest_asyncio.fixture
async def sender(keys: VapidKeys) -> AsyncIterator[PywebpushSender]:
    sender = PywebpushSender(
        vapid_private_key=keys.private_key,
        subject="mailto:ops@ihsu.uz",
        ttl_seconds=3600,
        timeout_seconds=5,
    )
    try:
        yield sender
    finally:
        await sender.close()


async def test_the_message_is_encrypted_for_the_device_and_signed_with_vapid(
    push_service: PushService, sender: PywebpushSender, keys: VapidKeys
) -> None:
    """The service worker can decrypt it, and the push service can verify us."""
    payload = json.dumps({"title": "Новые оценки", "url": "https://my.ihsu.uz/grades/"})

    await sender.send(push_service.subscription(), payload)

    assert push_service.plaintexts == [payload]
    (headers,) = push_service.requests
    assert headers["Content-Encoding"] == "aes128gcm"
    assert headers["ttl"] == "3600"
    scheme, _, rest = headers["Authorization"].partition(" ")
    parts = dict(item.split("=", 1) for item in rest.split(","))
    assert scheme == "vapid" and parts["k"] == keys.public_key
    claims = json.loads(_unb64(parts["t"].split(".")[1]))
    assert claims["sub"] == "mailto:ops@ihsu.uz"
    assert (
        claims["aud"] == f"http://{push_service.server.host}:{push_service.server.port}"
    )


@pytest.mark.parametrize("status", [404, 410])
async def test_not_found_and_gone_mean_the_subscription_is_dead(
    push_service: PushService, sender: PywebpushSender, status: int
) -> None:
    """404 and 410 are the push service's way to say 'unsubscribed'."""
    with pytest.raises(PushGone):
        await sender.send(push_service.subscription(status), "{}")


@pytest.mark.parametrize("status", [400, 403, 413, 429, 500, 503])
async def test_other_statuses_are_failures_to_retry(
    push_service: PushService, sender: PywebpushSender, status: int
) -> None:
    """Everything else is counted and retried by the dispatcher."""
    with pytest.raises(PushSendFailed) as caught:
        await sender.send(push_service.subscription(status), "{}")

    assert str(status) in str(caught.value)


async def test_an_unreachable_push_service_is_a_failure(
    push_service: PushService, sender: PywebpushSender
) -> None:
    """Connection errors do not delete the subscription."""
    subscription = push_service.subscription()
    await push_service.server.close()

    with pytest.raises(PushSendFailed):
        await sender.send(subscription, "{}")


async def test_keys_that_do_not_decode_are_a_failure_not_a_crash(
    push_service: PushService, sender: PywebpushSender
) -> None:
    """A garbage subscription must not stop the dispatcher."""
    subscription = push_service.subscription()
    subscription.p256dh = "not-a-key"

    with pytest.raises(PushSendFailed):
        await sender.send(subscription, "{}")
