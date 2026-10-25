"""MAIL-6: the aiosmtplib relay against a small SMTP server of our own."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.modules.mail.infrastructure.relay.aiosmtplib_relay import AiosmtplibRelay
from app.modules.mail.ports.outbound_relay import (
    RelayPermanentError,
    RelayResult,
    RelayTemporaryError,
)
from app.settings import SmtpOutSettings
from tests.mail.helpers import make_raw

import aiosmtplib
import pytest
from aiosmtpd.smtp import SMTP
from pydantic import SecretStr


class Relay:
    """A recording SMTP server; reply codes per recipient/DATA are configurable."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, list[str], bytes]] = []
        self.rcpt_replies: dict[str, str] = {}
        self.data_reply = "250 OK"

    async def handle_RCPT(  # noqa: N802
        self, server: Any, session: Any, envelope: Any, address: str, options: Any
    ) -> str:
        reply = self.rcpt_replies.get(address, "250 OK")
        if reply.startswith("250"):
            envelope.rcpt_tos.append(address)
        return reply

    async def handle_DATA(  # noqa: N802
        self, server: Any, session: Any, envelope: Any
    ) -> str:
        if self.data_reply.startswith("250"):
            self.messages.append(
                (envelope.mail_from, list(envelope.rcpt_tos), envelope.content)
            )
        return self.data_reply


Start = Callable[[], Awaitable[tuple[Relay, int]]]


@pytest.fixture
async def server() -> AsyncIterator[Start]:
    """Start a recording server on a free port."""
    servers = []

    async def start() -> tuple[Relay, int]:
        relay = Relay()
        created = await asyncio.get_running_loop().create_server(
            lambda: SMTP(relay), host="127.0.0.1", port=0
        )
        servers.append(created)
        return relay, int(created.sockets[0].getsockname()[1])

    yield start
    for created in servers:
        created.close()
        await created.wait_closed()


def relay_for(port: int, **changes: Any) -> AiosmtplibRelay:
    return AiosmtplibRelay(
        SmtpOutSettings(
            host="127.0.0.1", port=port, mail_domain="mail.ihsu.uz", **changes
        )
    )


async def test_the_message_is_delivered_to_all_recipients(server: Start) -> None:
    """MAIL-6: envelope sender and recipients are explicit, the raw bytes unchanged."""
    recording, port = await server()
    raw = make_raw(subject="Hi")

    result = await relay_for(port).send(
        sender="aleksey.brastilov@mail.ihsu.uz",
        recipients=["a@example.org", "b@example.org"],
        raw=raw,
    )

    assert result == RelayResult()
    [(sender, recipients, content)] = recording.messages
    assert sender == "aleksey.brastilov@mail.ihsu.uz"
    assert recipients == ["a@example.org", "b@example.org"]
    assert b"Subject: Hi" in content


async def test_a_refused_recipient_is_reported_when_the_others_were_accepted(
    server: Start,
) -> None:
    """MAIL-6: partial success keeps the mail `sent`."""
    recording, port = await server()
    recording.rcpt_replies["bad@example.org"] = "550 5.1.1 no such user"

    result = await relay_for(port).send(
        sender="a@mail.ihsu.uz",
        recipients=["good@example.org", "bad@example.org"],
        raw=make_raw(),
    )

    assert result.refused == ("bad@example.org",)
    assert recording.messages[0][1] == ["good@example.org"]


async def test_all_recipients_refused_with_5xx_is_permanent(server: Start) -> None:
    """MAIL-6: the relay will never take it."""
    recording, port = await server()
    recording.rcpt_replies["bad@example.org"] = "550 5.1.1 no such user"

    with pytest.raises(RelayPermanentError):
        await relay_for(port).send(
            sender="a@mail.ihsu.uz", recipients=["bad@example.org"], raw=make_raw()
        )


async def test_all_recipients_refused_with_4xx_is_temporary(server: Start) -> None:
    """MAIL-6: greylisting and busy servers are retried."""
    recording, port = await server()
    recording.rcpt_replies["slow@example.org"] = "450 4.2.0 try later"

    with pytest.raises(RelayTemporaryError):
        await relay_for(port).send(
            sender="a@mail.ihsu.uz", recipients=["slow@example.org"], raw=make_raw()
        )


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ("554 5.7.1 rejected as spam", RelayPermanentError),
        ("451 4.3.0 local error", RelayTemporaryError),
    ],
)
async def test_a_data_rejection_is_classified_by_its_code(
    server: Start, reply: str, error: type[Exception]
) -> None:
    """MAIL-6: 5xx permanent, 4xx temporary."""
    recording, port = await server()
    recording.data_reply = reply

    with pytest.raises(error):
        await relay_for(port).send(
            sender="a@mail.ihsu.uz", recipients=["a@example.org"], raw=make_raw()
        )


async def test_a_closed_port_is_temporary() -> None:
    """MAIL-6: connection errors are retried."""
    with pytest.raises(RelayTemporaryError):
        await relay_for(1).send(
            sender="a@mail.ihsu.uz", recipients=["a@example.org"], raw=make_raw()
        )


async def test_a_wrong_password_keeps_the_mail_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAIL-6: authentication errors are our configuration problem: temporary."""

    async def refuse(*args: Any, **kwargs: Any) -> Any:
        raise aiosmtplib.SMTPAuthenticationError(535, "bad credentials")

    monkeypatch.setattr(aiosmtplib, "send", refuse)

    with pytest.raises(RelayTemporaryError):
        await relay_for(587, username="u", password=SecretStr("p")).send(
            sender="a@mail.ihsu.uz", recipients=["a@example.org"], raw=make_raw()
        )


@pytest.mark.parametrize(
    ("port", "starttls", "expected"),
    [
        (1025, False, {"start_tls": False, "use_tls": False}),
        (587, True, {"start_tls": True, "use_tls": False}),
        (465, True, {"start_tls": False, "use_tls": True}),
    ],
)
async def test_tls_settings_follow_the_port_and_the_starttls_flag(
    monkeypatch: pytest.MonkeyPatch,
    port: int,
    starttls: bool,
    expected: dict[str, bool],
) -> None:
    """MAIL-6: STARTTLS on 587, implicit TLS on 465, none for Mailpit."""
    seen: dict[str, Any] = {}

    async def capture(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        seen.update(kwargs)
        return {}, "OK"

    monkeypatch.setattr(aiosmtplib, "send", capture)

    await relay_for(
        port, starttls=starttls, username="u", password=SecretStr("secret")
    ).send(sender="a@mail.ihsu.uz", recipients=["a@example.org"], raw=make_raw())

    assert {k: seen[k] for k in expected} == expected
    assert seen["username"] == "u" and seen["password"] == "secret"
    assert seen["local_hostname"] == "mail.ihsu.uz"
