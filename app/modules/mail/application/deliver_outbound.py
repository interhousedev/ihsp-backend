"""Hand a queued mail to the external relay with retries (MAIL-6)."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.modules.mail.ports.outbound_relay import (
    OutboundRelay,
    RelayPermanentError,
    RelayResult,
    RelayTemporaryError,
)
from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.base_error import GoneError, NotFoundError
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.key_lock import KeyLock
from app.shared.notifications import NotificationDraft, NotificationType

import structlog

log = structlog.get_logger(__name__)

RETRY_DELAYS = (2.0, 10.0, 30.0)
LOCK_SECONDS = 900
Sleep = Callable[[float], Awaitable[None]]


def _lock_key(mail_id: UUID) -> str:
    return f"mail:send:{mail_id}"


class DeliverOutbound:
    """Send the raw message; record sent or failed (and tell the student on failure)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        relay: OutboundRelay,
        lock: KeyLock,
        clock: Clock,
        sleep: Sleep = asyncio.sleep,
        delays: Sequence[float] = RETRY_DELAYS,
    ) -> None:
        """Store the dependencies; ``delays`` are the waits before each retry.

        ``lock`` keeps two workers from sending the same mail (`mail:send:{id}`).
        """
        self._uow_factory = uow_factory
        self._files = files
        self._relay = relay
        self._lock = lock
        self._clock = clock
        self._sleep = sleep
        self._delays = tuple(delays)

    async def execute(self, mail_id: UUID) -> None:
        """Send once; a mail that is not queued (or is being sent) is left alone."""
        async with self._uow_factory() as uow:
            mail = await uow.mail.get(mail_id)
        if mail is None or mail.direction != MailDirection.OUT:
            return
        if mail.status != MailStatus.QUEUED:
            return
        token = await self._lock.acquire(_lock_key(mail_id), LOCK_SECONDS)
        if token is None:
            return
        try:
            await self._deliver(mail)
        finally:
            await self._lock.release(_lock_key(mail_id), token)

    async def _deliver(self, mail: MailMessage) -> None:
        refused: list[str] = []
        failure: str | None = None
        try:
            result = await self._send_with_retries(mail)
            refused = list(result.refused)
        except (RelayTemporaryError, RelayPermanentError) as exc:
            failure = str(exc) or type(exc).__name__
        except (GoneError, NotFoundError):
            failure = "raw message is gone"
        await self._record(mail.id, failure, refused)

    async def _send_with_retries(self, mail: MailMessage) -> RelayResult:
        if mail.raw_file_id is None:
            raise RelayPermanentError("no raw message")
        raw = await self._files.read_bytes(mail.raw_file_id)
        recipients = [*mail.to, *mail.cc]
        for delay in self._delays:
            try:
                return await self._relay.send(
                    sender=mail.from_address, recipients=recipients, raw=raw
                )
            except RelayTemporaryError:
                log.warning("mail_relay_retry", mail_id=str(mail.id), delay=delay)
                await self._sleep(delay)
        return await self._relay.send(
            sender=mail.from_address, recipients=recipients, raw=raw
        )

    async def _record(
        self, mail_id: UUID, failure: str | None, refused: list[str]
    ) -> None:
        async with self._uow_factory() as uow:
            mail = await uow.mail.get(mail_id)
            if mail is None or mail.status != MailStatus.QUEUED:
                return
            if failure is None:
                mail.mark_sent(self._clock.now(), refused)
            else:
                mail.mark_failed(failure)
                uow.notify(
                    NotificationDraft(
                        user_id=mail.user_id,
                        type=NotificationType.MAIL_BOUNCED,
                        payload={"mail_id": str(mail.id), "to": list(mail.to)},
                        dedupe_key=f"mail-bounced:{mail.id}",
                    )
                )
            await uow.mail.save(mail)
            await uow.commit()
        log.info("mail_delivered", mail_id=str(mail_id), failed=failure is not None)
