"""Mark a received mail as spam, or take the mark back (UF-MAIL-04)."""

from uuid import UUID

from app.modules.mail.domain.errors import MailNotFoundError, NotAnInboundMailError
from app.modules.mail.domain.mail_status import MailStatus
from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import NotificationDraft, NotificationType


class MarkSpam:
    """Toggle spam; a mail taken out of spam is forwarded if it never was."""

    def __init__(self, *, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._identity = identity

    async def execute(self, user_id: UUID, mail_id: UUID, *, spam: bool) -> None:
        """Set the status; outbound mails cannot be marked."""
        forward = False if spam else await self._forwards(user_id)
        async with self._uow_factory() as uow:
            mail = await uow.mail.get_owned(user_id, mail_id)
            if mail is None:
                raise MailNotFoundError()
            if not mail.is_inbound():
                raise NotAnInboundMailError()
            was_spam = mail.status == MailStatus.SPAM
            mail.status = MailStatus.SPAM if spam else MailStatus.RECEIVED
            await uow.mail.save(mail)
            if was_spam and not spam and forward:
                # The dedupe key makes this a no-op when it was forwarded before.
                uow.notify(
                    NotificationDraft(
                        user_id=user_id,
                        type=NotificationType.MAIL,
                        payload={"mail_id": str(mail.id)},
                        dedupe_key=f"mail:{mail.id}",
                    )
                )
            await uow.commit()

    async def _forwards(self, user_id: UUID) -> bool:
        return (await self._identity.get_preferences(user_id)).mail_forward_to_telegram
