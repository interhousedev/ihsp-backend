"""Shared part of send, reply and forward: checks, limits, build, store, queue."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.mail.application.config import MailConfig
from app.modules.mail.application.kicks import SEND_OUTBOUND, kick_after_commit
from app.modules.mail.application.recipients import validate_recipients
from app.modules.mail.domain.errors import (
    MailboxUnavailableError,
    MailDailyLimitError,
    MailGlobalLimitError,
    MailSuspendedError,
    MailTooLargeError,
)
from app.modules.mail.domain.inbound_message import Attachment
from app.modules.mail.domain.mail_message import SNIPPET_LENGTH, MailMessage
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.modules.mail.domain.outbound_message import (
    MAX_OUTBOUND_BYTES,
    OutboundDraft,
    build_message,
    new_message_id,
)
from app.modules.mail.domain.telegram_html import html_to_text
from app.modules.mail.ports.suspension import MailSuspensionReader
from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.base_error import RateLimitedError
from app.shared.clock import Clock, local_today
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.contracts.identity import IdentityDirectory, UserStatus
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

DAY_SECONDS = 86400


@dataclass(frozen=True, slots=True)
class OutboundRequest:
    """What a use case asks the queue to send."""

    to: Sequence[str]
    subject: str
    html: str
    in_reply_to: str | None = None
    references: Sequence[str] = ()
    attachments: Sequence[Attachment] = field(default_factory=tuple)


class QueueOutbound:
    """Check the rules, build the message, keep the raw file and queue delivery."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        identity: IdentityDirectory,
        suspension: MailSuspensionReader,
        rate_limiter: RateLimiter,
        clock: Clock,
        kicker: TaskKicker,
        config: MailConfig,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files
        self._identity = identity
        self._suspension = suspension
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._kicker = kicker
        self._config = config

    async def execute(self, user_id: UUID, request: OutboundRequest) -> MailMessage:
        """Queue the mail for delivery and return its row."""
        recipients = validate_recipients(request.to, self._config.recipients_limit)
        user = await self._identity.get_user(user_id)
        if user is None or user.status != UserStatus.ACTIVE or not user.login:
            raise MailboxUnavailableError()
        if await self._suspension.is_suspended(user_id):
            raise MailSuspendedError()
        mail_id = new_id()
        now = self._clock.now()
        message_id = new_message_id(mail_id, self._config.mail_domain)
        raw = build_message(
            OutboundDraft(
                display_name=f"{user.first_name} {user.last_name}".strip(),
                login=user.login,
                domain=self._config.mail_domain,
                to=recipients,
                subject=request.subject,
                html=request.html,
                message_id=message_id,
                sent_at=now,
                in_reply_to=request.in_reply_to,
                references=request.references,
                attachments=request.attachments,
            )
        )
        if len(raw) > MAX_OUTBOUND_BYTES:
            raise MailTooLargeError()
        await self._count_against_limits(user_id)
        stored = await self._files.store_bytes(
            owner_id=user_id,
            scope=FileScope.MAIL,
            purpose=FilePurpose.MAIL,
            name=f"{mail_id}.eml",
            data=raw,
            expires_days=self._config.retention_days,
        )
        mail = MailMessage(
            id=mail_id,
            user_id=user_id,
            direction=MailDirection.OUT,
            message_id=message_id,
            from_address=f"{user.login}@{self._config.mail_domain}".lower(),
            occurred_at=now,
            status=MailStatus.QUEUED,
            to=recipients,
            subject=request.subject,
            snippet=" ".join(html_to_text(request.html).split())[:SNIPPET_LENGTH],
            in_reply_to=request.in_reply_to,
            references=list(request.references),
            raw_file_id=stored.id,
            attachment_file_ids=[],
        )
        async with self._uow_factory() as uow:
            await uow.mail.add(mail)
            uow.after_commit(kick_after_commit(self._kicker, SEND_OUTBOUND, mail_id))
            await uow.commit()
        return mail

    async def _count_against_limits(self, user_id: UUID) -> None:
        today = local_today(self._clock).isoformat()
        try:
            await self._rate_limiter.hit(
                f"mail:{user_id}:{today}",
                limit=self._config.per_day_limit,
                window_seconds=DAY_SECONDS,
            )
        except RateLimitedError as exc:
            raise MailDailyLimitError(
                params={"limit": self._config.per_day_limit}
            ) from exc
        try:
            await self._rate_limiter.hit(
                f"mail-global:{today}",
                limit=self._config.global_per_day_limit,
                window_seconds=DAY_SECONDS,
            )
        except RateLimitedError as exc:
            raise MailGlobalLimitError() from exc
