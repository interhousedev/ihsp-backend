"""GET /v1/id/me: the caller's account."""

from dataclasses import dataclass

from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.photo_files import PhotoSourceName, PhotoUrls
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


@dataclass(frozen=True, slots=True)
class MeView:
    """The account with its mailbox address."""

    user: User
    mailbox: str | None
    photo_url: str | None = None
    photo_source: PhotoSourceName | None = None


@dataclass(frozen=True, slots=True)
class GetMe:
    """Read the caller's own account."""

    uow_factory: UowFactory
    mail_domain: str
    photos: PhotoUrls

    async def execute(self, actor: Actor) -> MeView:
        """Return the account view."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
        return MeView(
            user=user,
            mailbox=self.mailbox_of(user),
            photo_url=await self.photos.url(user.photo_file_id),
            photo_source=await self.photos.source(user.photo_file_id),
        )

    def mailbox_of(self, user: User) -> str | None:
        """Students get {login}@mail domain (MAIL-1)."""
        if user.login and Role.STUDENT in user.roles:
            return f"{user.login}@{self.mail_domain}"
        return None
