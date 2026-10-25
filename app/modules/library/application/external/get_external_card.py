"""The card of one UniLibrary record, stored or not."""

from app.modules.library.application.external.cards import SOURCE, ExternalCards
from app.modules.library.application.external.gate import ExternalGate
from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.access import can_view
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import EventKind
from app.modules.library.domain.errors import (
    ExternalUnavailableError,
    ItemNotFoundError,
)
from app.modules.library.domain.external_lifecycle import clear_gone, mark_gone
from app.modules.library.ports.external_catalog import ExternalCatalog, ExternalRecord
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


class GetExternalCard:
    """LIB-12: `GET /library/external/unilibrary/{external_id}?category=`.

    A stored (pinned) record answers with its item's card and is marked `gone` when
    UniLibrary no longer has it (and unmarked when it is back). A record that is not
    stored is read from UniLibrary and not saved.
    """

    def __init__(
        self,
        *,
        gate: ExternalGate,
        catalog: ExternalCatalog,
        uow_factory: UowFactory,
        cards: ExternalCards,
        identity: IdentityDirectory,
        clock: Clock,
    ) -> None:
        """Take the gate, the catalogue and the card builder."""
        self.gate = gate
        self.catalog = catalog
        self.uow_factory = uow_factory
        self.cards = cards
        self.identity = identity
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        external_id: str,
        *,
        category: int,
        accept_language: str | None = None,
    ) -> ItemCardView:
        """The card; `ItemNotFoundError` when nobody has the record or it is hidden."""
        await self.gate.ensure_enabled()
        locale = await resolve_locale(self.identity, actor, accept_language)
        stored = await self._stored_card(actor, external_id, locale)
        try:
            record, _stale = await self.catalog.get(
                external_id, category=category, language=locale
            )
        except ExternalUnavailableError:
            if stored is None:
                raise
            return stored
        if stored is None:
            return await self._unstored_card(actor, record, locale)
        if await self._follow_upstream(external_id, present=record is not None):
            refreshed = await self._stored_card(actor, external_id, locale)
            return refreshed or stored
        return stored

    async def _stored_card(
        self, actor: Actor, external_id: str, locale: str
    ) -> ItemCardView | None:
        async with self.uow_factory() as uow:
            item = await uow.items.get_by_external(SOURCE, external_id)
            if item is None:
                return None
            if not can_view(item, actor):
                raise ItemNotFoundError
            (card,) = await self.cards.cards.build(
                uow, [item], viewer=actor, locale=locale
            )
            return card

    async def _unstored_card(
        self, actor: Actor, record: ExternalRecord | None, locale: str
    ) -> ItemCardView:
        if record is None:
            raise ItemNotFoundError
        async with self.uow_factory() as uow:
            (card,) = await self.cards.build(uow, [record], viewer=actor, locale=locale)
        return card

    async def _follow_upstream(self, external_id: str, *, present: bool) -> bool:
        """Mark the stored item gone or back; True when something changed."""
        async with self.uow_factory() as uow:
            item = await uow.items.get_by_external(SOURCE, external_id)
            if item is None:
                return False
            changed = await self._apply(uow, item, present=present)
            if changed:
                await uow.commit()
            return changed

    async def _apply(
        self, uow: LibraryUnitOfWork, item: Item, *, present: bool
    ) -> bool:
        now = self.clock.now()
        changed = clear_gone(item, now) if present else mark_gone(item, now)
        if changed:
            await uow.items.save(item)
            await uow.events.append(
                item.id, EventKind.SYNCED, at=now, data={"gone": not present}
            )
        return changed
