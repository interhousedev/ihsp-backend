"""The mail module wired for real (wiring.build, PostgreSQL), end to end."""

from dataclasses import dataclass
from uuid import UUID

from app.interfaces.smtp.handler import InboundHandler
from app.interfaces.smtp.server import start_smtp_server
from app.modules.mail.domain.mail_status import MailStatus
from app.modules.mail.infrastructure.auth.authenticator import DnsInboundAuthenticator
from app.modules.mail.infrastructure.relay.aiosmtplib_relay import AiosmtplibRelay
from app.modules.mail.wiring import MailServices, build
from app.settings import Settings, SmtpInSettings
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationType
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.outbox import InMemoryOutbox
from tests.fakes.tasks import FakeTaskKicker
from tests.mail.fakes import (
    FakeAuthenticator,
    FakeFilesApi,
    FakeIdentity,
    FakeRelay,
    FakeSuspension,
    RecordingSleep,
)
from tests.mail.helpers import ADDRESS, PDF_BYTES, fixture_bytes, make_raw

import aiosmtplib
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(slots=True)
class Stack:
    """Real use cases over PostgreSQL, fake neighbours."""

    services: MailServices
    outbox: InMemoryOutbox
    identity: FakeIdentity
    files: FakeFilesApi
    suspension: FakeSuspension
    relay: FakeRelay
    kicker: FakeTaskKicker
    clock: FixedClock
    student: UserRef


@pytest.fixture
def stack(
    settings: Settings,
    i18n: I18nCore,
    redis: Redis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> Stack:
    """wiring.build over the test database with an in-memory outbox."""
    outbox = InMemoryOutbox()
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=outbox.write_notifications,
        audit_writer=outbox.write_audit,
        outbox_committed_hook=None,
    )
    identity, files, suspension, relay = (
        FakeIdentity(),
        FakeFilesApi(),
        FakeSuspension(),
        FakeRelay(),
    )
    services = build(
        deps,
        identity=identity,
        files=files,
        suspension=suspension,
        authenticator=FakeAuthenticator(),
        relay=relay,
        sleep=RecordingSleep(),
    )
    student = identity.add_student()
    return Stack(
        services, outbox, identity, files, suspension, relay, kicker, clock, student
    )


async def receive(stack: Stack, raw: bytes) -> UUID:
    created = await stack.services.receive_inbound.execute(
        raw,
        peer_ip="203.0.113.9",
        helo="mx.example.com",
        mail_from="anna@example.com",
        recipients=[ADDRESS],
    )
    assert len(created) == 1
    await stack.services.parse_inbound.execute(created[0])
    return created[0]


async def test_default_wiring_uses_the_real_dns_checks_and_the_smtp_relay(
    settings: Settings,
    i18n: I18nCore,
    redis: Redis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """MAIL-6, MAIL-9: build() without test doubles creates the real adapters."""
    outbox = InMemoryOutbox()
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=outbox.write_notifications,
        audit_writer=outbox.write_audit,
        outbox_committed_hook=None,
    )

    services = build(
        deps, identity=FakeIdentity(), files=FakeFilesApi(), suspension=FakeSuspension()
    )

    receiver = services.receive_inbound
    assert isinstance(receiver._authenticator, DnsInboundAuthenticator)  # noqa: SLF001
    assert isinstance(services.deliver_outbound._relay, AiosmtplibRelay)  # noqa: SLF001
    assert services.public.address_of("a.b") == "a.b@mail.ihsu.uz"


async def test_a_received_mail_is_parsed_listed_and_announced(stack: Stack) -> None:
    """MAIL-2, MAIL-3: receive -> parse -> list -> view, with the real repository."""
    mail_id = await receive(stack, fixture_bytes("pdf_and_exe.eml"))

    page = await stack.services.public.recent(stack.student.id)
    view = await stack.services.public.view(stack.student.id, mail_id)

    assert [m.id for m in page] == [mail_id]
    assert page[0].subject == "Report and installer"
    assert page[0].snippet.startswith("The report is attached")
    assert [a.name for a in view["attachments"]] == ["report.pdf"]
    assert view["skipped_attachments"] == ["setup.exe"]
    assert [(n.user_id, n.type, n.dedupe_key) for n in stack.outbox.notifications] == [
        (stack.student.id, NotificationType.MAIL, f"mail:{mail_id}")
    ]


async def test_a_duplicate_delivery_is_ignored_by_the_database(stack: Stack) -> None:
    """MAIL-9: the unique (user, direction, Message-ID) index."""
    raw = fixture_bytes("plain.eml")
    await receive(stack, raw)

    again = await stack.services.receive_inbound.execute(
        raw,
        peer_ip="1.2.3.4",
        helo="x",
        mail_from="a@example.com",
        recipients=[ADDRESS],
    )

    assert again == []
    assert len(await stack.services.public.recent(stack.student.id)) == 1


async def test_send_deliver_and_bounce_end_to_end(stack: Stack) -> None:
    """MAIL-4, MAIL-6: send -> relay -> DSN -> bounced + notification."""
    summary = await stack.services.public.send(
        stack.student.id,
        to=["nobody@example.org"],
        subject="Question about the course",
        html="Hello",
    )
    await stack.services.deliver_outbound.execute(summary.id)
    sent = await stack.services.public.recent(stack.student.id)
    message_id = f"<{summary.id.hex}@mail.ihsu.uz>"

    dsn = fixture_bytes("dsn_bounce.eml").replace(
        b"@@ORIGINAL_ID@@", message_id.encode()
    )
    await receive(stack, dsn)

    assert stack.relay.calls[0].recipients == ("nobody@example.org",)
    assert [m.direction for m in sent] == ["out"]
    types = [n.type for n in stack.outbox.notifications]
    assert types == [NotificationType.MAIL_BOUNCED]
    async with stack.services.deliver_outbound._uow_factory() as uow:  # noqa: SLF001
        row = await uow.mail.get(summary.id)
    assert row is not None and row.status == MailStatus.BOUNCED


async def test_five_bounces_suspend_the_mailbox_in_the_database(stack: Stack) -> None:
    """MAIL-8: >= 5 bounces in 24 h -> MailSuspender, mail_suspended, audit."""
    for number in range(5):
        summary = await stack.services.public.send(
            stack.student.id,
            to=[f"gone{number}@example.org"],
            subject=f"s{number}",
            html="x",
        )
        await stack.services.deliver_outbound.execute(summary.id)
        dsn = (
            fixture_bytes("dsn_bounce.eml")
            .replace(b"@@ORIGINAL_ID@@", f"<{summary.id.hex}@mail.ihsu.uz>".encode())
            .replace(
                b"<dsn-1@relay.example.net>",
                f"<dsn-{number}@relay.example.net>".encode(),
            )
        )
        await receive(stack, dsn)
    stack.outbox.notifications.clear()

    suspended = await stack.services.check_bounces.execute()

    assert suspended == [stack.student.id]
    assert stack.student.id in stack.suspension.reasons
    assert [n.type for n in stack.outbox.notifications] == [
        NotificationType.MAIL_SUSPENDED
    ]
    assert [a.type for a in stack.outbox.audits] == ["mail.suspended"]
    assert await stack.services.check_bounces.execute() == []


async def test_reply_and_forward_use_the_stored_raw_mail(stack: Stack) -> None:
    """MAIL-4: reply keeps the thread; forward carries the attachments."""
    mail_id = await receive(
        stack,
        make_raw(
            attachments=[("a.pdf", "application/pdf", PDF_BYTES)],
            message_id="<orig@example.com>",
        ),
    )

    reply = await stack.services.public.reply(stack.student.id, mail_id, html="Thanks")
    forward = await stack.services.public.forward(
        stack.student.id, mail_id, to=["friend@example.org"], note_html=None
    )

    assert reply.subject == "Re: Hello" and forward.subject == "Fwd: Hello"
    await stack.services.deliver_outbound.execute(reply.id)
    await stack.services.deliver_outbound.execute(forward.id)
    assert b"In-Reply-To: <orig@example.com>" in stack.relay.calls[0].raw
    assert b'filename="a.pdf"' in stack.relay.calls[1].raw


async def test_purge_and_sweep_work_on_the_real_tables(stack: Stack) -> None:
    """MAIL-5, MAIL-7: jsonb merge, spam delete, stale queries."""
    kept = await receive(stack, fixture_bytes("plain.eml"))
    queued = await stack.services.public.send(
        stack.student.id, to=["a@example.org"], subject="x", html="x"
    )
    stack.clock.advance(minutes=11)
    stack.kicker.calls.clear()

    swept = await stack.services.sweep_mail.execute()
    stack.clock.advance(days=31)
    purged = await stack.services.purge_mail.execute()

    assert (swept.parse, swept.send) == (0, 1)
    assert stack.kicker.calls == [("mail.send_outbound", {"mail_id": queued.id})]
    assert purged.flagged == 2
    page = await stack.services.public.recent(stack.student.id)
    assert {m.id: m.purged for m in page} == {kept: True, queued.id: True}


async def test_a_message_goes_through_the_smtp_server_into_the_database(
    stack: Stack,
) -> None:
    """MAIL-9: socket -> aiosmtpd -> handler -> real repository."""
    services = stack.services
    handler = InboundHandler(
        resolve_mailbox=services.resolve_mailbox,
        receive_inbound=services.receive_inbound,
        max_recipients=20,
    )
    server = await start_smtp_server(
        handler, SmtpInSettings(), hostname="mx.mail.ihsu.uz", port=0, host="127.0.0.1"
    )
    try:
        port = int(server.sockets[0].getsockname()[1])
        await aiosmtplib.send(
            fixture_bytes("plain.eml"),
            sender="anna@example.com",
            recipients=[ADDRESS],
            hostname="127.0.0.1",
            port=port,
            local_hostname="client.example.com",
        )
    finally:
        server.close()
        await server.wait_closed()

    page = await services.public.recent(stack.student.id)
    assert [m.subject for m in page] == ["Meeting tomorrow"]
    assert stack.kicker.names() == ["mail.parse_inbound"]
