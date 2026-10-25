"""Find the student behind a mail address (MAIL-9)."""

from uuid import UUID

from app.modules.mail.application.config import MailConfig
from app.modules.mail.domain.addresses import login_from_address
from app.shared.actor import Role
from app.shared.contracts.identity import IdentityDirectory, UserStatus


class ResolveMailbox:
    """Accept only ``<login>@<mail domain>`` of an active student."""

    def __init__(self, *, identity: IdentityDirectory, config: MailConfig) -> None:
        """Store the dependencies."""
        self._identity = identity
        self._config = config

    async def execute(self, address: str) -> UUID | None:
        """Return the user id for an existing mailbox, else None."""
        login = login_from_address(address, self._config.mail_domain)
        if login is None:
            return None
        user = await self._identity.user_by_login(login)
        if user is None or user.status != UserStatus.ACTIVE:
            return None
        return user.id if Role.STUDENT in user.roles else None
