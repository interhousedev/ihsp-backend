"""Send an email from the platform to anyone (compose dialog), over SMTP."""

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from uuid import UUID

from app.modules.mail.application.recipients import validate_recipients
from app.modules.mail.domain.errors import (
    AttachmentNotFoundError,
    MailboxUnavailableError,
    MailDailyLimitError,
    MailTooLargeError,
    OutboundMailDisabledError,
)
from app.modules.mail.domain.outbound_message import MAX_OUTBOUND_BYTES
from app.modules.mail.ports.outbound_smtp import OutboundSmtp
from app.modules.mail.ports.unit_of_work import UowFactory
from app.settings import MailOutboundSettings
from app.shared.base_error import RateLimitedError
from app.shared.clock import Clock, local_today
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory, UserStatus
from app.shared.notifications import AuditDraft
from app.shared.rate_limit import RateLimiter

DAY_SECONDS = 86400
AUDIT_TYPE = "mail.outbound_sent"


@dataclass(frozen=True, slots=True)
class OutboundResult:
    """What was sent."""

    message_id: str
    to: tuple[str, ...]
    attachment_name: str | None


class SendOutbound:
    """Validate, rate-limit, send over SMTP and write an audit event."""

    def __init__(
        self,
        *,
        smtp: OutboundSmtp,
        identity: IdentityDirectory,
        files: FilesApi,
        rate_limiter: RateLimiter,
        uow_factory: UowFactory,
        clock: Clock,
        settings: MailOutboundSettings,
    ) -> None:
        """Store the dependencies."""
        self._smtp = smtp
        self._identity = identity
        self._files = files
        self._rate_limiter = rate_limiter
        self._uow_factory = uow_factory
        self._clock = clock
        self._settings = settings

    async def execute(
        self,
        user_id: UUID,
        *,
        to: list[str],
        subject: str,
        body: str,
        attachment_file_id: UUID | None = None,
    ) -> OutboundResult:
        """Send one email as the user (Reply-To is the user's own address)."""
        settings = self._settings
        if not settings.enabled:
            raise OutboundMailDisabledError()
        recipients = validate_recipients(to, settings.max_recipients)
        user = await self._identity.get_user(user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise MailboxUnavailableError()
        message = EmailMessage()
        display = f"{user.first_name} {user.last_name}".strip()
        message["From"] = formataddr((display, settings.from_address))
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject.strip()
        message["Date"] = formatdate(self._clock.now().timestamp(), localtime=False)
        domain = settings.from_address.rpartition("@")[2]
        message["Message-ID"] = make_msgid(domain=domain)
        message.set_content(body)
        attachment_name = await self._attach(message, user_id, attachment_file_id)
        if len(message.as_bytes()) > MAX_OUTBOUND_BYTES:
            raise MailTooLargeError()
        await self._count(user_id)
        await self._smtp.send(message)
        async with self._uow_factory() as uow:
            uow.audit(
                AuditDraft(
                    type=AUDIT_TYPE,
                    user_id=user_id,
                    actor_id=user_id,
                    metadata={
                        "to": recipients,
                        "subject": message["Subject"],
                        "attachment": attachment_name,
                    },
                )
            )
            await uow.commit()
        return OutboundResult(
            message_id=str(message["Message-ID"]),
            to=tuple(recipients),
            attachment_name=attachment_name,
        )

    async def _attach(
        self, message: EmailMessage, user_id: UUID, file_id: UUID | None
    ) -> str | None:
        if file_id is None:
            return None
        ref = await self._files.get(file_id)
        if ref is None or ref.owner_id != user_id:
            raise AttachmentNotFoundError()
        data = await self._files.read_bytes(file_id)
        maintype, _, subtype = (
            ref.content_type or "application/octet-stream"
        ).partition("/")
        message.add_attachment(
            data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=ref.name,
        )
        return ref.name

    async def _count(self, user_id: UUID) -> None:
        today = local_today(self._clock).isoformat()
        limit = self._settings.per_user_per_day
        try:
            await self._rate_limiter.hit(
                f"mail-outbound:{user_id}:{today}",
                limit=limit,
                window_seconds=DAY_SECONDS,
            )
        except RateLimitedError as exc:
            raise MailDailyLimitError(params={"limit": limit}) from exc
