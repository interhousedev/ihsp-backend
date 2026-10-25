"""Load a mail of the user and, when it still exists, its parsed raw message."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from app.modules.mail.domain.errors import MailNotFoundError
from app.modules.mail.domain.inbound_message import ParsedMail, parse_message
from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.base_error import GoneError, NotFoundError
from app.shared.contracts.files import FilesApi


@dataclass(frozen=True, slots=True)
class OriginalMail:
    """The row and, unless the raw file is gone, the parsed message."""

    mail: MailMessage
    parsed: ParsedMail | None


class LoadOriginal:
    """Reads a mail owned by the user together with its parsed raw message."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files

    async def row(self, user_id: UUID, mail_id: UUID) -> MailMessage:
        """Return the row or raise MailNotFoundError (also for other mailboxes)."""
        async with self._uow_factory() as uow:
            mail = await uow.mail.get_owned(user_id, mail_id)
        if mail is None:
            raise MailNotFoundError()
        return mail

    async def parsed(self, mail: MailMessage) -> ParsedMail | None:
        """Parse the raw file; None when it was deleted (30 days)."""
        if mail.raw_file_id is None:
            return None
        try:
            raw = await self._files.read_bytes(mail.raw_file_id)
        except (GoneError, NotFoundError):
            return None
        return await asyncio.to_thread(parse_message, raw)

    async def load(self, user_id: UUID, mail_id: UUID) -> OriginalMail:
        """Return the row and its parsed message."""
        mail = await self.row(user_id, mail_id)
        return OriginalMail(mail=mail, parsed=await self.parsed(mail))
