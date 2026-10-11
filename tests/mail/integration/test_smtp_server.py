"""MAIL-9: the real aiosmtpd server with the real handler, over a socket."""

import asyncio
import contextlib
import datetime as dt
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.interfaces.smtp.handler import InboundHandler
from app.interfaces.smtp.peer_limiter import PeerLimiter
from app.interfaces.smtp.server import (
    build_handler,
    build_tls_context,
    run_mail_server,
    start_smtp_server,
)
from app.modules.mail.domain.mail_status import MailStatus
from app.settings import Settings, SmtpInSettings
from app.shared.contracts.identity import UserRef
from tests.mail.helpers import ADDRESS, fixture_bytes, make_raw
from tests.mail.world import MailWorld

import aiosmtplib
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

Start = Callable[..., Awaitable[int]]
HELO = "client.example.com"


@pytest.fixture
async def smtp(
    world: MailWorld,
) -> AsyncIterator[Start]:
    """Start the server on a free port; call it with SmtpInSettings changes."""
    servers = []

    async def start(settings: SmtpInSettings | None = None) -> int:
        handler = InboundHandler(
            resolve_mailbox=world.resolve_mailbox,
            receive_inbound=world.receive_inbound,
            max_recipients=20,
        )
        server = await start_smtp_server(
            handler,
            settings or SmtpInSettings(),
            hostname="mx.mail.ihsu.uz",
            port=0,
            host="127.0.0.1",
        )
        servers.append(server)
        return int(server.sockets[0].getsockname()[1])

    yield start
    for server in servers:
        server.close()
        await server.wait_closed()


async def deliver(
    port: int,
    raw: bytes,
    recipients: list[str],
    *,
    mail_from: str = "anna@example.com",
    **options: object,
) -> tuple[dict[str, aiosmtplib.SMTPResponse], str]:
    return await aiosmtplib.send(
        raw,
        sender=mail_from,
        recipients=recipients,
        hostname="127.0.0.1",
        port=port,
        local_hostname=HELO,
        **options,  # type: ignore[arg-type]
    )


async def test_mail_for_an_existing_mailbox_is_accepted_and_stored(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9: 250 after the raw mail is stored and parsing is queued."""
    port = await smtp()

    refused, reply = await deliver(port, fixture_bytes("plain.eml"), [ADDRESS])

    assert refused == {}
    assert reply == "OK queued"
    [row] = world.store.all()
    assert row.user_id == student.id and row.status == MailStatus.RECEIVED
    assert row.subject == "Meeting tomorrow"
    assert world.kicker.names() == ["mail.parse_inbound"]


async def test_the_peer_address_sender_and_helo_reach_the_checks(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9: SPF needs the connecting IP, MAIL FROM and the HELO name."""
    port = await smtp()

    await deliver(
        port, fixture_bytes("plain.eml"), [ADDRESS], mail_from="bounce@example.com"
    )

    assert world.authenticator.calls == [
        {"peer_ip": "127.0.0.1", "mail_from": "bounce@example.com", "helo": HELO}
    ]


async def test_an_unknown_login_is_refused_with_550_5_1_1(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9, UF-MAIL-01 1b: unknown recipients are refused during SMTP."""
    port = await smtp()

    with pytest.raises(aiosmtplib.SMTPRecipientsRefused) as raised:
        await deliver(port, fixture_bytes("plain.eml"), ["nobody@mail.ihsu.uz"])

    [refusal] = raised.value.recipients
    assert refusal.code == 550
    assert "5.1.1" in refusal.message
    assert world.store.rows == {}


async def test_another_domain_is_refused_too(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9: this server is not an open relay."""
    port = await smtp()

    with pytest.raises(aiosmtplib.SMTPRecipientsRefused) as raised:
        await deliver(port, fixture_bytes("plain.eml"), ["aleksey.brastilov@gmail.com"])

    assert raised.value.recipients[0].code == 550


async def test_a_good_and_a_bad_recipient_deliver_to_the_good_one(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9: refusal is per recipient."""
    port = await smtp()

    refused, _ = await deliver(
        port, fixture_bytes("plain.eml"), [ADDRESS, "nobody@mail.ihsu.uz"]
    )

    assert list(refused) == ["nobody@mail.ihsu.uz"]
    assert refused["nobody@mail.ihsu.uz"].code == 550
    assert len(world.store.rows) == 1


async def test_more_than_twenty_recipients_are_refused_with_452(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9: at most 20 recipients per message."""
    port = await smtp()

    refused, _ = await deliver(port, fixture_bytes("plain.eml"), [ADDRESS] * 21)

    assert [r.code for r in refused.values()] == [452]
    assert len(world.store.rows) == 1


async def test_a_message_over_the_size_limit_is_refused_with_552(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9: up to SMTP_IN__MAX_BYTES (25 MB; lowered to 20 KB here)."""
    port = await smtp(SmtpInSettings(max_bytes=20_000))
    big = make_raw(body="x" * 40_000)

    with pytest.raises(aiosmtplib.SMTPResponseException) as raised:
        await deliver(port, big, [ADDRESS])

    assert raised.value.code == 552
    assert world.store.rows == {}


async def test_a_30_megabyte_message_is_refused_with_the_default_limit(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9: the 25 MB default; a 30 MB message is refused with 552."""
    port = await smtp()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "anna@example.com", ADDRESS, "Big"
    msg["Message-ID"] = "<big-1@example.com>"
    msg.set_content("see attachment")
    msg.add_attachment(
        b"0" * (30 * 1024 * 1024),
        maintype="application",
        subtype="pdf",
        filename="big.pdf",
    )

    with pytest.raises(aiosmtplib.SMTPResponseException) as raised:
        await deliver(port, msg.as_bytes(), [ADDRESS])

    assert raised.value.code == 552
    assert world.store.rows == {}


async def test_an_internal_error_asks_the_sender_to_retry_later(
    world: MailWorld, student: UserRef, smtp: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAIL-9: 451 (temporary), never a lost message."""
    port = await smtp()

    async def broken(**kwargs: object) -> None:
        raise RuntimeError("S3 is down")

    monkeypatch.setattr(world.files, "store_bytes", broken)

    with pytest.raises(aiosmtplib.SMTPResponseException) as raised:
        await deliver(port, fixture_bytes("plain.eml"), [ADDRESS])

    assert raised.value.code == 451
    assert world.store.rows == {}


def _certificate(directory: Path) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mx.mail.ihsu.uz")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


async def test_starttls_is_offered_when_a_certificate_is_configured(
    world: MailWorld, student: UserRef, smtp: Start, tmp_path: Path
) -> None:
    """MAIL-9: over TLS when the sender supports it."""
    cert, key = _certificate(tmp_path)
    port = await smtp(SmtpInSettings(tls_cert_path=cert, tls_key_path=key))

    await deliver(
        port,
        fixture_bytes("plain.eml"),
        [ADDRESS],
        start_tls=True,
        validate_certs=False,
    )

    assert len(world.store.rows) == 1


async def test_senders_without_tls_are_still_accepted(
    world: MailWorld, student: UserRef, smtp: Start, tmp_path: Path
) -> None:
    """MAIL-9: STARTTLS is optional for an MX."""
    cert, key = _certificate(tmp_path)
    port = await smtp(SmtpInSettings(tls_cert_path=cert, tls_key_path=key))

    await deliver(port, fixture_bytes("plain.eml"), [ADDRESS], start_tls=False)

    assert len(world.store.rows) == 1


async def test_starttls_is_not_offered_without_a_certificate(
    world: MailWorld, student: UserRef, smtp: Start
) -> None:
    """MAIL-9: no cert/key -> no STARTTLS."""
    port = await smtp()

    with pytest.raises(aiosmtplib.SMTPException):
        await deliver(
            port,
            fixture_bytes("plain.eml"),
            [ADDRESS],
            start_tls=True,
            validate_certs=False,
        )


def test_no_tls_context_without_both_files() -> None:
    """MAIL-9: a half configuration means no TLS."""
    assert build_tls_context(SmtpInSettings(tls_cert_path="/x/cert.pem")) is None
    assert build_tls_context(SmtpInSettings()) is None


async def test_a_failing_mailbox_lookup_is_a_temporary_failure(
    world: MailWorld, student: UserRef, smtp: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAIL-9: identity down -> 451 at RCPT, so the sender retries (not 550)."""
    port = await smtp()

    async def down(login: str) -> None:
        raise RuntimeError("identity is down")

    monkeypatch.setattr(world.identity, "user_by_login", down)

    with pytest.raises(aiosmtplib.SMTPRecipientsRefused) as raised:
        await deliver(port, fixture_bytes("plain.eml"), [ADDRESS])

    assert raised.value.recipients[0].code == 451


class _Envelope:
    def __init__(self, content: object, original: object = None) -> None:
        self.content = content
        self.original_content = original
        self.mail_from = "anna@example.com"
        self.rcpt_tos = [ADDRESS]


class _Session:
    def __init__(self, peer: object) -> None:
        self.peer = peer
        self.host_name = None


@pytest.mark.parametrize(
    ("peer", "expected_ip"),
    [
        (("203.0.113.9", 4000), "203.0.113.9"),
        (("2001:db8::1", 4000, 0, 0), "2001:db8::1"),
        ("/run/smtp.sock", "/run/smtp.sock"),
        (None, ""),
    ],
)
async def test_the_handler_copes_with_text_content_and_unusual_peers(
    world: MailWorld, student: UserRef, peer: object, expected_ip: str
) -> None:
    """MAIL-9: IPv6 peers are 4-tuples; unix sockets give a path."""
    handler = InboundHandler(
        resolve_mailbox=world.resolve_mailbox,
        receive_inbound=world.receive_inbound,
        max_recipients=20,
    )

    reply = await handler.handle_DATA(
        None, _Session(peer), _Envelope(None, fixture_bytes("plain.eml").decode())
    )

    assert reply == "250 OK queued"
    assert world.authenticator.calls[0]["peer_ip"] == expected_ip
    assert world.authenticator.calls[0]["helo"] == ""


async def test_a_peer_probing_many_logins_gets_450_instead_of_550(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: after twenty unknown mailboxes a peer learns nothing more."""
    handler = InboundHandler(
        resolve_mailbox=world.resolve_mailbox,
        receive_inbound=world.receive_inbound,
        max_recipients=20,
        limiter=PeerLimiter(unknown_limit=2),
    )
    probe, other = _Session(("203.0.113.9", 4000)), _Session(("203.0.113.10", 4000))

    async def rcpt(session: _Session, address: str) -> str:
        envelope = _Envelope(None)
        envelope.rcpt_tos = []
        return await handler.handle_RCPT(None, session, envelope, address, [])

    first = await rcpt(probe, "nobody@mail.ihsu.uz")
    second = await rcpt(probe, "someone@mail.ihsu.uz")
    blocked_unknown = await rcpt(probe, "another@mail.ihsu.uz")
    blocked_known = await rcpt(probe, ADDRESS)
    known_from_elsewhere = await rcpt(other, ADDRESS)

    assert first.startswith("550 5.1.1") and second.startswith("550 5.1.1")
    assert blocked_unknown.startswith("450 4.7.1")
    assert blocked_known.startswith("450 4.7.1")
    assert known_from_elsewhere == "250 OK"


async def test_a_peer_sending_too_many_messages_is_told_to_wait(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: a per-peer message limit; the message is not stored."""
    handler = InboundHandler(
        resolve_mailbox=world.resolve_mailbox,
        receive_inbound=world.receive_inbound,
        max_recipients=20,
        limiter=PeerLimiter(messages_limit=1),
    )
    session = _Session(("203.0.113.9", 4000))
    raw = fixture_bytes("plain.eml")

    first = await handler.handle_DATA(None, session, _Envelope(raw))
    second = await handler.handle_DATA(None, session, _Envelope(raw))

    assert first == "250 OK queued"
    assert second.startswith("450 4.7.1")
    assert len(world.store.rows) == 1


async def test_build_handler_takes_the_use_cases_from_the_container(
    world: MailWorld,
) -> None:
    """MAIL-9: container.mail supplies resolve_mailbox, receive_inbound and config."""
    handler = build_handler(SimpleNamespace(mail=world))  # type: ignore[arg-type]

    assert handler._max_recipients == 20  # noqa: SLF001


async def test_run_mail_server_serves_until_cancelled(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: `python -m app mail` runs this coroutine."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = Settings(smtp_in=SmtpInSettings(host="127.0.0.1", port=port))
    container: Any = SimpleNamespace(mail=world, settings=settings)
    task = asyncio.create_task(run_mail_server(container))
    try:
        for _ in range(50):
            try:
                await deliver(port, fixture_bytes("plain.eml"), [ADDRESS])
                break
            except OSError:
                await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(world.store.rows) == 1
