"""Finding the language of a user."""

from uuid import UUID

from app.shared.contracts.identity import IdentityDirectory

DEFAULT_LOCALE = "ru"


class LocaleResolver:
    """Reads a user's locale from the identity directory."""

    def __init__(self, identity: IdentityDirectory) -> None:
        """Store the directory."""
        self.identity = identity

    async def locale_of(self, user_id: UUID) -> str:
        """Return the user's locale, `ru` when the user is unknown."""
        user = await self.identity.get_user(user_id)
        return user.locale if user is not None else DEFAULT_LOCALE
