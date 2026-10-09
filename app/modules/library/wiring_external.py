"""Builds the external (UniLibrary) area of the library."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.modules.library.application.external.cards import ExternalCards
from app.modules.library.application.external.create_feed import CreateFeed
from app.modules.library.application.external.delete_feed import DeleteFeed
from app.modules.library.application.external.gate import ExternalGate
from app.modules.library.application.external.get_external_card import GetExternalCard
from app.modules.library.application.external.get_field_map import GetFieldMap
from app.modules.library.application.external.get_status import GetStatus
from app.modules.library.application.external.get_taxonomies import GetTaxonomies
from app.modules.library.application.external.get_unilibrary_settings import (
    GetUniLibrarySettings,
)
from app.modules.library.application.external.list_feeds import ListFeeds
from app.modules.library.application.external.pin_external import PinExternal
from app.modules.library.application.external.put_field_map import PutFieldMap
from app.modules.library.application.external.put_unilibrary_settings import (
    PutUniLibrarySettings,
)
from app.modules.library.application.external.run_feed_action import RunFeedAction
from app.modules.library.application.external.search_external import SearchExternal
from app.modules.library.application.external.update_feed import UpdateFeed
from app.modules.library.infrastructure.unilibrary.factory import build_unilibrary
from app.modules.library.ports.external_catalog import ExternalCatalog
from app.modules.library.wiring_core import LibraryCore


@dataclass(frozen=True, slots=True)
class ExternalServices:
    """Use cases of the UniLibrary area (a switched-off base: link-only records).

    `gate.flags()` gives the effective `enabled` and `anonymous_cards` (the runtime
    override beats the environment); other areas that show UniLibrary items ask it.
    `closers` close the HTTP pool at shutdown.
    """

    gate: ExternalGate
    catalog: ExternalCatalog
    search: SearchExternal
    get_card: GetExternalCard
    pin: PinExternal
    get_taxonomies: GetTaxonomies
    get_settings: GetUniLibrarySettings
    put_settings: PutUniLibrarySettings
    get_status: GetStatus
    list_feeds: ListFeeds
    create_feed: CreateFeed
    update_feed: UpdateFeed
    delete_feed: DeleteFeed
    run_feed_action: RunFeedAction
    get_field_map: GetFieldMap
    put_field_map: PutFieldMap
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)


def build_external(
    core: LibraryCore, *, catalog: ExternalCatalog | None = None
) -> ExternalServices:
    """Wire the use cases; tests pass a fake `catalog`, production builds the client.

    Nothing calls UniLibrary while `LIBRARY__UNILIBRARY_ENABLED` is false and
    Administration has not switched it on.
    """
    stack = build_unilibrary(core.settings, core.deps.redis, core.clock)
    source = catalog or stack.catalog
    gate = ExternalGate(core.settings, stack.flags)
    cards = ExternalCards(cards=core.cards, academic=core.academic)
    return ExternalServices(
        gate=gate,
        catalog=source,
        search=SearchExternal(
            gate=gate,
            catalog=source,
            uow_factory=core.uow_factory,
            cards=cards,
            identity=core.identity,
            rate_limiter=core.rate_limiter,
            clock=core.clock,
            searches_per_minute=core.settings.unilibrary_user_searches_per_min,
        ),
        get_card=GetExternalCard(
            gate=gate,
            catalog=source,
            uow_factory=core.uow_factory,
            cards=cards,
            identity=core.identity,
            clock=core.clock,
        ),
        pin=PinExternal(
            gate=gate,
            catalog=source,
            uow_factory=core.uow_factory,
            cards=cards,
            identity=core.identity,
            clock=core.clock,
        ),
        get_taxonomies=GetTaxonomies(
            gate=gate, catalog=source, identity=core.identity, i18n=core.i18n
        ),
        get_settings=GetUniLibrarySettings(gate),
        put_settings=PutUniLibrarySettings(stack.flags),
        get_status=GetStatus(
            monitor=stack.monitor,
            uow_factory=core.uow_factory,
            cards=core.cards,
            identity=core.identity,
        ),
        list_feeds=ListFeeds(core.uow_factory),
        create_feed=CreateFeed(core.uow_factory, core.clock),
        update_feed=UpdateFeed(core.uow_factory, core.clock),
        delete_feed=DeleteFeed(core.uow_factory),
        run_feed_action=RunFeedAction(core.uow_factory, core.clock),
        get_field_map=GetFieldMap(core.uow_factory),
        put_field_map=PutFieldMap(core.uow_factory, core.academic),
        closers=[stack.aclose],
    )
