"""Pin a UniLibrary record: store its snapshot so it can go on a shelf or a list."""

from uuid import UUID

from app.modules.library.application.external.cards import SOURCE, ExternalCards
from app.modules.library.application.external.gate import ExternalGate
from app.modules.library.application.external.snapshot import build_pinned_item
from app.modules.library.application.external.views import PinResult
from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.access import can_view
from app.modules.library.domain.entities import Item, SubjectLink
from app.modules.library.domain.enums import EventKind
from app.modules.library.domain.errors import DuplicateItemError, ItemNotFoundError
from app.modules.library.ports.external_catalog import ExternalCatalog, ExternalRecord
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id


class PinExternal:
    """LIB-7, LIB-12: `POST /library/external/unilibrary/{external_id}/item`.

    Idempotent: a record that is stored already answers with its item. A new pin
    keeps facts only (never files), as a published item the whole lyceum can see.
    Nobody owns it; the pinning user is `created_by`.
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
    ) -> PinResult:
        """The card of the stored item and whether this call stored it."""
        await self.gate.ensure_enabled()
        locale = await resolve_locale(self.identity, actor, accept_language)
        existing = await self._existing(actor, external_id, locale)
        if existing is not None:
            return existing
        record, _stale = await self.catalog.get(
            external_id, category=category, language=locale
        )
        if record is None:
            raise ItemNotFoundError
        return await self._store(actor, record, locale)

    async def _existing(
        self, actor: Actor, external_id: str, locale: str
    ) -> PinResult | None:
        async with self.uow_factory() as uow:
            item = await uow.items.get_by_external(SOURCE, external_id)
            if item is None:
                return None
            return PinResult(await self._card(uow, item, actor, locale), False)

    async def _store(
        self, actor: Actor, record: ExternalRecord, locale: str
    ) -> PinResult:
        now = self.clock.now()
        item = build_pinned_item(
            record, item_id=new_id(), actor_id=actor.user_id, now=now, locale=locale
        )
        async with self.uow_factory() as uow:
            try:
                await uow.external.add_pinned(item)
            except DuplicateItemError:
                # Someone pinned the record between our check and our insert.
                winner = await uow.items.get_by_external(SOURCE, record.external_id)
                if winner is None:
                    raise
                return PinResult(await self._card(uow, winner, actor, locale), False)
            await uow.items.set_subject_links(
                item.id, await self._subject_links(uow, record)
            )
            await uow.events.append(
                item.id,
                EventKind.CREATED,
                at=now,
                actor_id=actor.user_id,
                data={"source": "unilibrary", "external_id": record.external_id},
            )
            card = await self._card(uow, item, actor, locale)
            await uow.commit()
        return PinResult(card, True)

    async def _subject_links(
        self, uow: LibraryUnitOfWork, record: ExternalRecord
    ) -> list[SubjectLink]:
        """The subjects whose mapped field is the record's field."""
        if record.field_id is None:
            return []
        subject_ids: list[UUID] = [
            entry.subject_id
            for entry in await uow.external.field_map()
            if entry.external_field_id == record.field_id
        ]
        return [SubjectLink(subject_id) for subject_id in dict.fromkeys(subject_ids)]

    async def _card(
        self, uow: LibraryUnitOfWork, item: Item, actor: Actor, locale: str
    ) -> ItemCardView:
        if not can_view(item, actor):
            raise ItemNotFoundError
        (card,) = await self.cards.cards.build(uow, [item], viewer=actor, locale=locale)
        return card
