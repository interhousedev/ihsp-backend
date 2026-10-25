"""MAIL-4, MAIL-6: outbound mail reaches the relay (Mailpit of the dev compose)."""

import asyncio
from typing import Any

from app.modules.mail.wiring import MailServices, build
from app.settings import Settings
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.outbox import InMemoryOutbox
from tests.fakes.tasks import FakeTaskKicker
from tests.mail.fakes import FakeFilesApi, FakeIdentity, FakeSuspension
from tests.mail.helpers import PDF_BYTES, make_raw

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

MAILPIT = "http://localhost:8025/api/v1"


@pytest.fixture
def mail(
    settings: Settings,
    i18n: I18nCore,
    redis: Redis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> tuple[MailServices, FakeIdentity, FakeFilesApi]:
    """The real module with the real aiosmtplib relay (SMTP_OUT__* = Mailpit)."""
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
    identity, files = FakeIdentity(), FakeFilesApi()
    services = build(deps, identity=identity, files=files, suspension=FakeSuspension())
    return services, identity, files


async def find_in_mailpit(subject: str) -> dict[str, Any]:
    """Wait until Mailpit lists a message with the subject; return its full record."""
    async with httpx.AsyncClient(base_url=MAILPIT, timeout=5) as client:
        for _ in range(50):
            found = await client.get(
                "/search", params={"query": f'subject:"{subject}"'}
            )
            found.raise_for_status()
            messages = found.json()["messages"]
            if messages:
                full = await client.get(f"/message/{messages[0]['ID']}")
                full.raise_for_status()
                record: dict[str, Any] = full.json()
                headers = await client.get(f"/message/{messages[0]['ID']}/headers")
                record["HeadersMap"] = headers.json()
                return record
            await asyncio.sleep(0.1)
    raise AssertionError(f"no message with subject {subject!r} reached Mailpit")


async def test_a_sent_mail_arrives_at_the_relay(
    mail: tuple[MailServices, FakeIdentity, FakeFilesApi],
) -> None:
    """MAIL-4, MAIL-6: From, To, Subject, HTML and plain bodies at Mailpit."""
    services, identity, _ = mail
    student = identity.add_student()
    subject = "Mailpit check A1 Вопрос"

    summary = await services.public.send(
        student.id,
        to=["teacher@example.org"],
        subject=subject,
        html="Hello <b>teacher</b>",
    )
    await services.deliver_outbound.execute(summary.id)
    record = await find_in_mailpit(subject)

    assert record["From"]["Address"] == "aleksey.brastilov@mail.ihsu.uz"
    assert record["From"]["Name"] == "Aleksey Brastilov"
    assert [t["Address"] for t in record["To"]] == ["teacher@example.org"]
    assert record["Subject"] == subject
    assert "Hello teacher" in record["Text"]
    assert "<b>teacher</b>" in record["HTML"]
    assert record["HeadersMap"]["Message-Id"] == [f"<{summary.id.hex}@mail.ihsu.uz>"]


async def test_a_reply_arrives_with_the_thread_headers(
    mail: tuple[MailServices, FakeIdentity, FakeFilesApi],
) -> None:
    """MAIL-4: In-Reply-To and References reach the recipient."""
    services, identity, _ = mail
    student = identity.add_student()
    created = await services.receive_inbound.execute(
        make_raw(subject="Mailpit check B2", message_id="<thread-1@example.com>"),
        peer_ip="203.0.113.9",
        helo="mx.example.com",
        mail_from="anna@example.com",
        recipients=["aleksey.brastilov@mail.ihsu.uz"],
    )
    await services.parse_inbound.execute(created[0])

    reply = await services.public.reply(student.id, created[0], html="Thanks, Anna")
    await services.deliver_outbound.execute(reply.id)
    record = await find_in_mailpit("Re: Mailpit check B2")

    assert [t["Address"] for t in record["To"]] == ["anna@example.com"]
    assert record["HeadersMap"]["In-Reply-To"] == ["<thread-1@example.com>"]
    assert record["HeadersMap"]["References"] == ["<thread-1@example.com>"]


async def test_a_forward_arrives_with_its_attachment(
    mail: tuple[MailServices, FakeIdentity, FakeFilesApi],
) -> None:
    """MAIL-2, MAIL-4: the original attachments travel with the forward."""
    services, identity, _ = mail
    student = identity.add_student()
    created = await services.receive_inbound.execute(
        make_raw(
            subject="Mailpit check C3",
            message_id="<fwd-1@example.com>",
            attachments=[("notes.pdf", "application/pdf", PDF_BYTES)],
        ),
        peer_ip="203.0.113.9",
        helo="mx.example.com",
        mail_from="anna@example.com",
        recipients=["aleksey.brastilov@mail.ihsu.uz"],
    )
    await services.parse_inbound.execute(created[0])

    forward = await services.public.forward(
        student.id, created[0], to=["friend@example.org"], note_html="FYI"
    )
    await services.deliver_outbound.execute(forward.id)
    record = await find_in_mailpit("Fwd: Mailpit check C3")

    assert [a["FileName"] for a in record["Attachments"]] == ["notes.pdf"]
    assert record["Text"].startswith("FYI")
