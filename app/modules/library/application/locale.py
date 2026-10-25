"""Which language names and labels are shown in: the profile, else the header."""

from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory

SUPPORTED = ("uz", "ru", "en")
DEFAULT_LOCALE = "ru"


def parse_accept_language(header: str | None) -> str | None:
    """The first supported language of an `Accept-Language` header, or None."""
    if not header:
        return None
    for part in header.split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in SUPPORTED:
            return code
    return None


async def resolve_locale(
    identity: IdentityDirectory, actor: Actor | None, accept_language: str | None = None
) -> str:
    """The user's profile language; for a visitor the header; else the default."""
    if actor is not None:
        user = await identity.get_user(actor.user_id)
        if user is not None and user.locale in SUPPORTED:
            return user.locale
    return parse_accept_language(accept_language) or DEFAULT_LOCALE
