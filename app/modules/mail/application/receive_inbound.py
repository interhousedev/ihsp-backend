"""Accept a message from the SMTP server: check, store, record (MAIL-9)."""

import hashlib
from collections.abc import Sequence
from uuid import UUID

from app.modules.mail.application.config import MailConfig
from app.modules.mail.application.kicks import PARSE_INBOUND, kick_after_commit
from app.modules.mail.application.resolve_mailbox import ResolveMailbox
from app.modules.mail.domain.inbound_message import (
    MailHeaders,
    body_is_empty,
    parse_headers,
)
from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.mail_meta import MailMeta
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.modules.mail.domain.spam import SpamVerdict, spam_verdict
from app.modules.mail.ports.inbound_authenticator import InboundAuthenticator
from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)


class ReceiveInbound:
    """Store one raw message per recipient mailbox and queue its parsing."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        authenticator: InboundAuthenticator,
        resolve_mailbox: ResolveMailbox,
        clock: Clock,
        kicker: TaskKicker,
        config: MailConfig,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files
        self._authenticator = authenticator
        self._resolve_mailbox = resolve_mailbox
        self._clock = clock
        self._kicker = kicker
        self._config = config

    async def execute(
        self,
        raw: bytes,
        *,
        peer_ip: str,
        helo: str,
        mail_from: str,
        recipients: Sequence[str],
    ) -> list[UUID]:
        """Return the ids of the mails created (duplicates are not created again)."""
        user_ids = await self._mailboxes(recipients)
        if not user_ids:
            return []
        headers = parse_headers(raw)
        checks = await self._authenticator.check(
            raw, peer_ip=peer_ip, mail_from=mail_from, helo=helo
        )
        verdict = spam_verdict(
            checks,
            has_message_id=headers.message_id is not None,
            is_empty=not headers.subject and body_is_empty(raw),
        )
        meta = MailMeta(checks=checks, spam_reasons=list(verdict.reasons))
        message_id = headers.message_id or self._synthetic_id(raw)
        created: list[UUID] = []
        for user_id in user_ids:
            mail_id = await self._store(
                user_id, raw, headers, message_id, mail_from, verdict, meta
            )
            if mail_id is not None:
                created.append(mail_id)
        log.info("mail_received", mailboxes=len(user_ids), stored=len(created))
        return created

    async def _mailboxes(self, recipients: Sequence[str]) -> list[UUID]:
        found: dict[UUID, None] = {}
        for address in recipients:
            user_id = await self._resolve_mailbox.execute(address)
            if user_id is not None:
                found[user_id] = None
        return list(found)

    def _synthetic_id(self, raw: bytes) -> str:
        """A stable id for mail without one, so a retried delivery is a duplicate."""
        digest = hashlib.sha256(raw).hexdigest()[:32]
        return f"<no-id-{digest}@{self._config.mail_domain}>"

    async def _store(
        self,
        user_id: UUID,
        raw: bytes,
        headers: MailHeaders,
        message_id: str,
        mail_from: str,
        verdict: SpamVerdict,
        meta: MailMeta,
    ) -> UUID | None:
        async with self._uow_factory() as uow:
            if await uow.mail.inbound_exists(user_id, message_id):
                return None
        mail_id = new_id()
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
            direction=MailDirection.IN,
            message_id=message_id,
            from_address=headers.from_address or mail_from,
            occurred_at=self._clock.now(),
            status=MailStatus.SPAM if verdict.is_spam else MailStatus.RECEIVED,
            to=list(headers.to),
            cc=list(headers.cc),
            subject=headers.subject,
            in_reply_to=headers.in_reply_to,
            references=list(headers.references),
            raw_file_id=stored.id,
            spam_score=verdict.score,
            meta=meta.model_copy(deep=True),
        )
        async with self._uow_factory() as uow:
            if not await uow.mail.add(mail):
                return None
            uow.after_commit(kick_after_commit(self._kicker, PARSE_INBOUND, mail_id))
            await uow.commit()
        return mail_id
