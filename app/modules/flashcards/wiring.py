"""Builds the flashcards module: use cases and the public `FlashcardsApi`."""

from dataclasses import dataclass

from app.modules.flashcards.application.add_cards import AddCards
from app.modules.flashcards.application.copy_from_share import CopyFromShare
from app.modules.flashcards.application.create_set import CreateSet
from app.modules.flashcards.application.delete_set import DeleteSet
from app.modules.flashcards.application.get_set import GetSet
from app.modules.flashcards.application.list_sets import ListSets
from app.modules.flashcards.application.public_api import FlashcardsApiImpl
from app.modules.flashcards.application.replace_cards import ReplaceCards
from app.modules.flashcards.application.review_card import ReviewCard
from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.study_next import StudyNext
from app.modules.flashcards.application.update_card import UpdateCard
from app.modules.flashcards.application.update_set import UpdateSet
from app.modules.flashcards.infrastructure.redis_daily_counters import (
    RedisDailyCounters,
)
from app.modules.flashcards.infrastructure.uow import SqlFlashcardsUnitOfWork
from app.modules.flashcards.ports.daily_counters import DailyCounters
from app.modules.flashcards.ports.share_resolver import ShareResolver
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class FlashcardsServices:
    """Use cases of the flashcards module (attribute name = use case file name)."""

    create_set: CreateSet
    list_sets: ListSets
    get_set: GetSet
    update_set: UpdateSet
    delete_set: DeleteSet
    replace_cards: ReplaceCards
    add_cards: AddCards
    update_card: UpdateCard
    study_next: StudyNext
    review_card: ReviewCard
    copy_from_share: CopyFromShare
    public: FlashcardsApi


@dataclass(frozen=True, slots=True)
class FlashcardsOverrides:
    """Replacements for the SQL unit of work and the Redis counters (for tests)."""

    uow_factory: UowFactory | None = None
    counters: DailyCounters | None = None


def build(
    deps: ModuleDeps,
    *,
    links: ShareResolver,
    overrides: FlashcardsOverrides | None = None,
) -> FlashcardsServices:
    """Wire the module.

    `links` answers `resolve_share(slug) -> (kind, target_id) | None`; the links
    module builds after this one, so the composition root passes a lazy proxy.
    """
    over = overrides or FlashcardsOverrides()
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    counters = over.counters or RedisDailyCounters(deps.redis)
    views = SetViews(clock=deps.clock, counters=counters)
    create_set = CreateSet(uow_factory=uow_factory, clock=deps.clock, views=views)
    list_sets = ListSets(uow_factory=uow_factory, clock=deps.clock, views=views)
    add_cards = AddCards(uow_factory=uow_factory, views=views)
    update_card = UpdateCard(uow_factory=uow_factory)
    return FlashcardsServices(
        create_set=create_set,
        list_sets=list_sets,
        get_set=GetSet(uow_factory=uow_factory, views=views),
        update_set=UpdateSet(uow_factory=uow_factory, views=views),
        delete_set=DeleteSet(uow_factory=uow_factory),
        replace_cards=ReplaceCards(uow_factory=uow_factory, views=views),
        add_cards=add_cards,
        update_card=update_card,
        study_next=StudyNext(uow_factory=uow_factory, views=views),
        review_card=ReviewCard(
            uow_factory=uow_factory, clock=deps.clock, counters=counters, views=views
        ),
        copy_from_share=CopyFromShare(
            uow_factory=uow_factory, clock=deps.clock, links=links, views=views
        ),
        public=FlashcardsApiImpl(
            uow_factory=uow_factory,
            list_sets=list_sets,
            create_set=create_set,
            add_cards=add_cards,
            update_card=update_card,
        ),
    )


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlFlashcardsUnitOfWork:
        return SqlFlashcardsUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
