"""GET /v1/id/me: the caller's account."""

from dataclasses import dataclass

from app.modules.identity.application.load_user import require_user
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


@dataclass(frozen=True, slots=True)
class MeView:
    """The account with its Telegram links and mailbox address."""

    user: User
    telegram: list[TelegramLink]
    mailbox: str | None


@dataclass(frozen=True, slots=True)
class GetMe:
    """Read the caller's own account."""

    uow_factory: UowFactory
    mail_domain: str

    async def execute(self, actor: Actor) -> MeView:
        """Return the account view."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            links = await uow.telegram_links.list_for_user(user.id)
        return MeView(user=user, telegram=links, mailbox=self.mailbox_of(user))

    def mailbox_of(self, user: User) -> str | None:
        """Students get {login}@mail domain (MAIL-1)."""
        if user.login and Role.STUDENT in user.roles:
            return f"{user.login}@{self.mail_domain}"
        return None
