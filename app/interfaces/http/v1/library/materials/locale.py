"""The language an answer is written in (profile first, then `Accept-Language`)."""

from app.modules.library.application.locale import resolve_locale
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor


async def locale_for(
    library: LibraryServices, actor: Actor, accept_language: str | None
) -> str:
    """`uz`, `ru` or `en` for names and labels in the answer."""
    return await resolve_locale(library.core.identity, actor, accept_language)
