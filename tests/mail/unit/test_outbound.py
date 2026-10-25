"""Outbound email from the platform: validation, SMTP, limits, audit."""

from email.message import EmailMessage

from app.modules.mail.application.list_sent_mail import ListSentMail
from app.modules.mail.application.send_outbound import AUDIT_TYPE, SendOutbound
from app.modules.mail.domain.errors import (
    AttachmentNotFoundError,
    InvalidRecipientError,
    MailDailyLimitError,
    NoRecipientsError,
    OutboundMailDisabledError,
    TooManyRecipientsError,
)
from app.modules.mail.domain.mail_status import MailStatus
from app.settings import MailOutboundSettings
from app.shared.actor import Role
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.contracts.identity import UserRef
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from tests.mail.fakes import FakeMailUnitOfWork
from tests.mail.helpers import PDF_BYTES
from tests.mail.world import MailWorld

import pytest
from redis.asyncio import Redis


class FakeSmtp:
    """OutboundSmtp that keeps what it was given."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


def build(
    world: MailWorld, redis: Redis, **overrides: object
) -> tuple[SendOutbound, FakeSmtp]:
    smtp = FakeSmtp()
    values: dict[str, object] = {"enabled": True, "from_address": "no-reply@ihsu.uz"}
    settings = MailOutboundSettings.model_validate({**values, **overrides})
    use_case = SendOutbound(
        smtp=smtp,
        identity=world.identity,
        files=world.files,
        rate_limiter=RateLimiter(redis),
        uow_factory=lambda: FakeMailUnitOfWork(world.store),
        clock=world.clock,
        settings=settings,
    )
    return use_case, smtp


async def test_an_email_goes_through_smtp_and_is_audited(
    world: MailWorld, redis: Redis, student: UserRef
) -> None:
    """The message is sent as the user and an audit event is written."""
    send, smtp = build(world, redis)

    result = await send.execute(
        student.id, to=[" Teacher@example.org "], subject=" Question ", body="Hello"
    )

    [message] = smtp.sent
    assert message["To"] == "Teacher@example.org"
    assert message["Subject"] == "Question"
    assert "Aleksey Brastilov" in message["From"]
    assert "no-reply@ihsu.uz" in message["From"]
    assert message.get_content().strip() == "Hello"
    assert result.to == ("Teacher@example.org",)
    [audit] = world.store.audits
    assert audit.type == AUDIT_TYPE
    assert audit.actor_id == student.id
    assert audit.metadata is not None
    assert audit.metadata["to"] == ["Teacher@example.org"]


async def test_a_file_from_my_files_is_attached(
    world: MailWorld, redis: Redis, student: UserRef
) -> None:
    """The attachment keeps its name and bytes."""
    stored = await world.files.store_bytes(
        owner_id=student.id,
        scope=FileScope.STUDENT,
        purpose=FilePurpose.MAIL,
        name="notes.pdf",
        data=PDF_BYTES,
        expires_days=None,
    )
    send, smtp = build(world, redis)

    result = await send.execute(
        student.id,
        to=["a@example.org"],
        subject="Notes",
        body="See file",
        attachment_file_id=stored.id,
    )

    [attachment] = list(smtp.sent[0].iter_attachments())
    assert attachment.get_filename() == "notes.pdf"
    assert attachment.get_content() == PDF_BYTES
    assert result.attachment_name == "notes.pdf"


async def test_someone_elses_file_cannot_be_attached(
    world: MailWorld, redis: Redis, student: UserRef
) -> None:
    """Only the sender's own files can be attached; nothing is sent."""
    other = world.student("other.user")
    stored = await world.files.store_bytes(
        owner_id=other.id,
        scope=FileScope.STUDENT,
        purpose=FilePurpose.MAIL,
        name="secret.pdf",
        data=PDF_BYTES,
        expires_days=None,
    )
    send, smtp = build(world, redis)

    with pytest.raises(AttachmentNotFoundError):
        await send.execute(
            student.id,
            to=["a@example.org"],
            subject="x",
            body="y",
            attachment_file_id=stored.id,
        )
    assert smtp.sent == []
    with pytest.raises(AttachmentNotFoundError):
        await send.execute(
            student.id,
            to=["a@example.org"],
            subject="x",
            body="y",
            attachment_file_id=new_id(),
        )


async def test_recipients_are_validated(
    world: MailWorld, redis: Redis, student: UserRef
) -> None:
    """A bad address, none, or too many are refused before sending."""
    send, smtp = build(world, redis, max_recipients=2)

    with pytest.raises(InvalidRecipientError):
        await send.execute(student.id, to=["not-an-email"], subject="s", body="b")
    with pytest.raises(NoRecipientsError):
        await send.execute(student.id, to=[" "], subject="s", body="b")
    with pytest.raises(TooManyRecipientsError):
        await send.execute(
            student.id,
            to=["a@example.org", "b@example.org", "c@example.org"],
            subject="s",
            body="b",
        )
    assert smtp.sent == []


async def test_the_daily_limit_is_per_user(
    world: MailWorld, redis: Redis, student: UserRef
) -> None:
    """The user's third mail of the day is refused; another user is unaffected."""
    send, smtp = build(world, redis, per_user_per_day=2)
    other = world.student("teacher.one", roles=frozenset({Role.TEACHER}))
    for _ in range(2):
        await send.execute(student.id, to=["a@example.org"], subject="s", body="b")

    with pytest.raises(MailDailyLimitError):
        await send.execute(student.id, to=["a@example.org"], subject="s", body="b")
    await send.execute(other.id, to=["a@example.org"], subject="s", body="b")

    assert len(smtp.sent) == 3


async def test_nothing_is_sent_while_the_feature_is_off(
    world: MailWorld, redis: Redis, student: UserRef
) -> None:
    """`IHSP_MAIL__OUTBOUND__ENABLED=false` refuses every send."""
    send, smtp = build(world, redis, enabled=False)

    with pytest.raises(OutboundMailDisabledError):
        await send.execute(student.id, to=["a@example.org"], subject="s", body="b")
    assert smtp.sent == []


async def test_sent_mail_is_listed_newest_first_and_only_for_the_sender(
    world: MailWorld, redis: Redis, student: UserRef
) -> None:
    """The Email page lists what the user sent, paged by time."""
    send, _ = build(world, redis)
    list_sent = ListSentMail(uow_factory=lambda: FakeMailUnitOfWork(world.store))
    for subject in ("First", "Second", "Third"):
        await send.execute(
            student.id, to=["t@example.org"], subject=subject, body="Hello  there"
        )
        world.clock.advance(minutes=1)

    page = await list_sent.execute(student.id, limit=2)
    assert [item.subject for item in page.items] == ["Third", "Second"]
    assert page.items[0].snippet == "Hello there"
    assert page.items[0].status == MailStatus.SENT
    assert page.next_before is not None
    rest = await list_sent.execute(student.id, limit=2, before=page.next_before)
    assert [item.subject for item in rest.items] == ["First"]
    assert rest.next_before is None
    assert (await list_sent.execute(new_id())).items == []
