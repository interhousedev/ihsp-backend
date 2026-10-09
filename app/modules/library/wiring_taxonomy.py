"""Builds the taxonomy area of the library: topics, collections, lists, statistics."""

from dataclasses import dataclass

from app.modules.library.application.taxonomy.collection_builder import (
    CollectionBuilder,
)
from app.modules.library.application.taxonomy.create_collection import (
    CreateCollection,
)
from app.modules.library.application.taxonomy.create_topic import CreateTopic
from app.modules.library.application.taxonomy.delete_collection import (
    DeleteCollection,
)
from app.modules.library.application.taxonomy.delete_topic import DeleteTopic
from app.modules.library.application.taxonomy.get_collection import GetCollection
from app.modules.library.application.taxonomy.list_collections import (
    ListCollections,
)
from app.modules.library.application.taxonomy.list_manage_collections import (
    ListManageCollections,
)
from app.modules.library.application.taxonomy.list_manage_topics import (
    ListManageTopics,
)
from app.modules.library.application.taxonomy.list_topics import ListTopics
from app.modules.library.application.taxonomy.update_collection import (
    UpdateCollection,
)
from app.modules.library.application.taxonomy.update_topic import UpdateTopic
from app.modules.library.wiring_core import LibraryCore


@dataclass(frozen=True, slots=True)
class TaxonomyServices:
    """Use cases of the taxonomy area."""

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


def build_taxonomy(core: LibraryCore) -> TaxonomyServices:
    """Wire the use cases of the taxonomy area."""
    collections = CollectionBuilder(
        files=core.files,
        cover_ttl_seconds=core.settings.reader_url_seconds,
        anonymous_cards=core.settings.unilibrary_anonymous_cards,
    )
    return TaxonomyServices(
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
    )
