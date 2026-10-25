"""The detail of one item by id or slug (GET /library/items/{id_or_slug})."""

from app.modules.library.application.catalogue.common import (
    anonymous_cards,
    load_visible,
)
from app.modules.library.application.detail import DetailBuilder, ItemDetailView
from app.modules.library.application.locale import resolve_locale
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class GetItem:
    """`ItemDetail` for the caller; `library/not-found` for anything not visible."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        detail: DetailBuilder,
        identity: IdentityDirectory,
        settings: LibrarySettings,
    ) -> None:
        """Store the unit of work factory, the detail builder and the settings."""
        self.uow_factory = uow_factory
        self.detail = detail
        self.identity = identity
        self.settings = settings

    async def execute(
        self, actor: Actor | None, ref: str, *, accept_language: str | None = None
    ) -> ItemDetailView:
        """The item with files, topics and what the caller may do with it."""
        cards = anonymous_cards(self.settings)
        locale = await resolve_locale(self.identity, actor, accept_language)
        async with self.uow_factory() as uow:
            item = await load_visible(uow, ref, actor, cards=cards)
            return await self.detail.build(
                uow, item, viewer=actor, locale=locale, anonymous_cards=cards
            )
