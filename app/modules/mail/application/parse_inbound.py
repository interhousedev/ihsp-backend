"""Parse a stored inbound mail: snippet, attachments, bounces, forwarding (MAIL-2)."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.mail.application.config import MailConfig
from app.modules.mail.domain.attachment_policy import (
    MAX_ATTACHMENTS,
    judge_attachment,
)
from app.modules.mail.domain.inbound_message import (
    Attachment,
    ParsedMail,
    parse_message,
)
from app.modules.mail.domain.mail_message import SNIPPET_LENGTH, MailMessage
from app.modules.mail.domain.mail_status import MailStatus
from app.modules.mail.ports.unit_of_work import MailUnitOfWork, UowFactory
from app.shared.base_error import BaseError, GoneError, NotFoundError
from app.shared.clock import Clock
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import NotificationDraft, NotificationType

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Read:
    """A parsed message and its snippet (both computed off the event loop)."""

    parsed: ParsedMail
    snippet: str


def _parse(raw: bytes) -> _Read:
    parsed = parse_message(raw)
    return _Read(parsed, " ".join(parsed.plain_text().split())[:SNIPPET_LENGTH])


class ParseInbound:
    """Fill in a received mail from its raw file and decide who is told about it."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        identity: IdentityDirectory,
        clock: Clock,
        config: MailConfig,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files
        self._identity = identity
        self._clock = clock
        self._config = config

    async def execute(self, mail_id: UUID) -> None:
        """Parse once; a repeated run (sweep, retry) does nothing."""
        async with self._uow_factory() as uow:
            mail = await uow.mail.get(mail_id)
        if mail is None or not mail.is_inbound() or mail.meta.parsed_at is not None:
            return
        read = await self._read(mail)
        stored: list[UUID] = []
        skipped: list[str] = []
        if read is not None:
            stored, skipped = await self._store_attachments(
                mail.user_id, read.parsed.attachments
            )
        forward = await self._wants_forwarding(mail)
        async with self._uow_factory() as uow:
            fresh = await uow.mail.get(mail_id)
            if fresh is None or fresh.meta.parsed_at is not None:
                return
            if read is not None:
                self._apply(fresh, read, stored, skipped)
            fresh.meta.parsed_at = self._clock.now()
            await uow.mail.save(fresh)
            await self._announce(
                uow, fresh, None if read is None else read.parsed, forward
            )
            await uow.commit()

    async def _read(self, mail: MailMessage) -> _Read | None:
        if mail.raw_file_id is None:
            return None
        try:
            raw = await self._files.read_bytes(mail.raw_file_id)
        except (GoneError, NotFoundError):
            log.warning("mail_raw_missing", mail_id=str(mail.id))
            return None
        return await asyncio.to_thread(_parse, raw)

    async def _wants_forwarding(self, mail: MailMessage) -> bool:
        if mail.status != MailStatus.RECEIVED:
            return False
        prefs = await self._identity.get_preferences(mail.user_id)
        return prefs.mail_forward_to_telegram

    async def _store_attachments(
        self, user_id: UUID, attachments: Sequence[Attachment]
    ) -> tuple[list[UUID], list[str]]:
        stored: list[UUID] = []
        skipped: list[str] = []
        for number, attachment in enumerate(attachments):
            if number >= MAX_ATTACHMENTS or not await self._keep(
                user_id, attachment, stored
            ):
                skipped.append(attachment.name)
        return stored, skipped

    async def _keep(
        self, user_id: UUID, attachment: Attachment, stored: list[UUID]
    ) -> bool:
        verdict = judge_attachment(
            attachment.name, attachment.content_type, attachment.data
        )
        if not verdict.allowed:
            return False
        try:
            ref = await self._files.store_bytes(
                owner_id=user_id,
                scope=FileScope.MAIL,
                purpose=FilePurpose.MAIL,
                name=attachment.name,
                data=attachment.data,
                expires_days=self._config.retention_days,
            )
        except BaseError:
            log.warning("mail_attachment_not_stored", name=attachment.name)
            return False
        stored.append(ref.id)
        return True

    def _apply(
        self,
        mail: MailMessage,
        read: _Read,
        stored: list[UUID],
        skipped: list[str],
    ) -> None:
        headers = read.parsed.headers
        mail.from_address = headers.from_address or mail.from_address
        mail.to = list(headers.to) or mail.to
        mail.cc = list(headers.cc)
        mail.subject = headers.subject
        mail.in_reply_to = headers.in_reply_to
        mail.references = list(headers.references)
        mail.snippet = read.snippet
        mail.attachment_file_ids = stored
        mail.meta.skipped_attachments = skipped

    async def _announce(
        self,
        uow: MailUnitOfWork,
        mail: MailMessage,
        parsed: ParsedMail | None,
        forward: bool,
    ) -> None:
        """Mark a bounced original, or else tell the student about the mail."""
        if parsed is not None and parsed.report is not None and parsed.report.failed:
            original = await uow.mail.find_outbound(
                mail.user_id, parsed.report.original_ids
            )
            if original is not None:
                await self._bounce(uow, original, parsed.report.reason)
                return
        if forward:
            uow.notify(
                NotificationDraft(
                    user_id=mail.user_id,
                    type=NotificationType.MAIL,
                    payload={"mail_id": str(mail.id)},
                    dedupe_key=f"mail:{mail.id}",
                )
            )

    async def _bounce(
        self, uow: MailUnitOfWork, original: MailMessage, reason: str | None
    ) -> None:
        original.mark_bounced(self._clock.now(), reason)
        await uow.mail.save(original)
        uow.notify(
            NotificationDraft(
                user_id=original.user_id,
                type=NotificationType.MAIL_BOUNCED,
                payload={"mail_id": str(original.id), "to": list(original.to)},
                dedupe_key=f"mail-bounced:{original.id}",
            )
        )
