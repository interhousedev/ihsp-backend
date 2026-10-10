"""Builds the taxonomy area of the library: topics, collections, lists, statistics."""

from dataclasses import dataclass

from app.modules.library.application.taxonomy.collection_builder import (
    CollectionBuilder,
)
from app.modules.library.application.taxonomy.create_collection import (
    CreateCollection,
)
from app.modules.library.application.taxonomy.create_reading_list import (
    CreateReadingList,
)
from app.modules.library.application.taxonomy.create_topic import CreateTopic
from app.modules.library.application.taxonomy.delete_collection import (
    DeleteCollection,
)
from app.modules.library.application.taxonomy.delete_reading_list import (
    DeleteReadingList,
)
from app.modules.library.application.taxonomy.delete_topic import DeleteTopic
from app.modules.library.application.taxonomy.get_collection import GetCollection
from app.modules.library.application.taxonomy.get_library_stats import GetLibraryStats
from app.modules.library.application.taxonomy.get_reading_list import GetReadingList
from app.modules.library.application.taxonomy.list_collections import (
    ListCollections,
)
from app.modules.library.application.taxonomy.list_manage_collections import (
    ListManageCollections,
)
from app.modules.library.application.taxonomy.list_manage_topics import (
    ListManageTopics,
)
from app.modules.library.application.taxonomy.list_my_groups import ListMyGroups
from app.modules.library.application.taxonomy.list_reading_lists import (
    ListReadingLists,
)
from app.modules.library.application.taxonomy.list_topics import ListTopics
from app.modules.library.application.taxonomy.manage_subjects import (
    CreateSubject,
    DeleteSubject,
    ListManageSubjects,
    UpdateSubject,
)
from app.modules.library.application.taxonomy.reading_list_builder import (
    ReadingListBuilder,
)
from app.modules.library.application.taxonomy.replace_list_entries import (
    ReplaceListEntries,
)
from app.modules.library.application.taxonomy.rollup_stats import RollupStats
from app.modules.library.application.taxonomy.update_collection import (
    UpdateCollection,
)
from app.modules.library.application.taxonomy.update_reading_list import (
    UpdateReadingList,
)
from app.modules.library.application.taxonomy.update_topic import UpdateTopic
from app.modules.library.infrastructure.redis_stats_reader import RedisStatsCounters
from app.modules.library.wiring_core import LibraryCore


@dataclass(frozen=True, slots=True)
class TaxonomyServices:
    """Use cases of the taxonomy area."""

    list_manage_subjects: ListManageSubjects
    create_subject: CreateSubject
    update_subject: UpdateSubject
    delete_subject: DeleteSubject
    list_topics: ListTopics
    list_manage_topics: ListManageTopics
    create_topic: CreateTopic
    update_topic: UpdateTopic
    delete_topic: DeleteTopic
    list_collections: ListCollections
    get_collection: GetCollection
    list_manage_collections: ListManageCollections
    create_collection: CreateCollection
    update_collection: UpdateCollection
    delete_collection: DeleteCollection
    list_my_groups: ListMyGroups
    list_reading_lists: ListReadingLists
    get_reading_list: GetReadingList
    create_reading_list: CreateReadingList
    update_reading_list: UpdateReadingList
    delete_reading_list: DeleteReadingList
    replace_list_entries: ReplaceListEntries
    get_stats: GetLibraryStats
    rollup_stats: RollupStats


def build_taxonomy(core: LibraryCore) -> TaxonomyServices:
    """Wire the use cases of the taxonomy area."""
    collections = CollectionBuilder(
        files=core.files,
        cover_ttl_seconds=core.settings.reader_url_seconds,
        anonymous_cards=core.settings.unilibrary_anonymous_cards,
    )
    lists = ReadingListBuilder(
        identity=core.identity,
        academic=core.academic,
        cards=core.cards,
        anonymous_cards=core.settings.unilibrary_anonymous_cards,
    )
    counters = RedisStatsCounters(core.deps.redis)
    return TaxonomyServices(
        list_manage_subjects=ListManageSubjects(uow_factory=core.uow_factory),
        create_subject=CreateSubject(uow_factory=core.uow_factory, clock=core.clock),
        update_subject=UpdateSubject(uow_factory=core.uow_factory, clock=core.clock),
        delete_subject=DeleteSubject(uow_factory=core.uow_factory),
        list_topics=ListTopics(uow_factory=core.uow_factory, identity=core.identity),
        list_manage_topics=ListManageTopics(uow_factory=core.uow_factory),
        create_topic=CreateTopic(
            uow_factory=core.uow_factory, academic=core.academic, clock=core.clock
        ),
        update_topic=UpdateTopic(uow_factory=core.uow_factory, clock=core.clock),
        delete_topic=DeleteTopic(uow_factory=core.uow_factory),
        list_collections=ListCollections(
            uow_factory=core.uow_factory, identity=core.identity, builder=collections
        ),
        get_collection=GetCollection(
            uow_factory=core.uow_factory,
            identity=core.identity,
            cards=core.cards,
            builder=collections,
        ),
        list_manage_collections=ListManageCollections(
            uow_factory=core.uow_factory, builder=collections
        ),
        create_collection=CreateCollection(
            uow_factory=core.uow_factory, clock=core.clock, builder=collections
        ),
        update_collection=UpdateCollection(
            uow_factory=core.uow_factory, clock=core.clock, builder=collections
        ),
        delete_collection=DeleteCollection(uow_factory=core.uow_factory),
        list_my_groups=ListMyGroups(academic=core.academic),
        list_reading_lists=ListReadingLists(
            uow_factory=core.uow_factory,
            identity=core.identity,
            academic=core.academic,
            builder=lists,
        ),
        get_reading_list=GetReadingList(
            uow_factory=core.uow_factory,
            identity=core.identity,
            academic=core.academic,
            builder=lists,
        ),
        create_reading_list=CreateReadingList(
            uow_factory=core.uow_factory,
            clock=core.clock,
            identity=core.identity,
            academic=core.academic,
            builder=lists,
        ),
        update_reading_list=UpdateReadingList(
            uow_factory=core.uow_factory,
            clock=core.clock,
            identity=core.identity,
            academic=core.academic,
            builder=lists,
        ),
        delete_reading_list=DeleteReadingList(uow_factory=core.uow_factory),
        replace_list_entries=ReplaceListEntries(
            uow_factory=core.uow_factory,
            clock=core.clock,
            identity=core.identity,
            builder=lists,
            max_items=core.settings.list_max_items,
            anonymous_cards=core.settings.unilibrary_anonymous_cards,
        ),
        get_stats=GetLibraryStats(
            uow_factory=core.uow_factory,
            clock=core.clock,
            identity=core.identity,
            academic=core.academic,
            cards=core.cards,
            counters=counters,
        ),
        rollup_stats=RollupStats(
            uow_factory=core.uow_factory, clock=core.clock, counters=counters
        ),
    )
