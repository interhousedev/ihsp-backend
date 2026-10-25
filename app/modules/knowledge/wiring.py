"""Builds the knowledge module: use cases over a unit of work, and its public search."""

from dataclasses import dataclass

from app.modules.knowledge.application.create_entry import CreateEntry
from app.modules.knowledge.application.delete_entry import DeleteEntry
from app.modules.knowledge.application.entry_indexer import (
    EmbeddingsProvider,
    EntryIndexer,
)
from app.modules.knowledge.application.get_entry import GetEntry
from app.modules.knowledge.application.knowledge_search import KnowledgeSearch
from app.modules.knowledge.application.list_entries import ListEntries
from app.modules.knowledge.application.public_api import KnowledgeSearchPort
from app.modules.knowledge.application.search_entries import SearchEntries
from app.modules.knowledge.application.update_entry import UpdateEntry
from app.modules.knowledge.infrastructure.uow import SqlKnowledgeUnitOfWork
from app.modules.knowledge.ports.unit_of_work import UowFactory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class KnowledgeServices:
    """Use cases of the knowledge module (attribute name = use case file name)."""

    list_entries: ListEntries
    create_entry: CreateEntry
    get_entry: GetEntry
    update_entry: UpdateEntry
    delete_entry: DeleteEntry
    search_entries: SearchEntries
    public: KnowledgeSearchPort
    """The same port `make_search_port` builds, ready to hand to other modules."""


@dataclass(frozen=True, slots=True)
class KnowledgeOverrides:
    """Replacement for the SQL unit of work (for tests)."""

    uow_factory: UowFactory | None = None


def build(
    deps: ModuleDeps,
    *,
    embeddings: EmbeddingsProvider,
    overrides: KnowledgeOverrides | None = None,
) -> KnowledgeServices:
    """Wire the module; `embeddings` returns the vectors index once it exists."""
    over = overrides or KnowledgeOverrides()
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    settings = deps.settings.knowledge
    indexer = EntryIndexer(embeddings=embeddings)
    search = SearchEntries(
        uow_factory=uow_factory, embeddings=embeddings, settings=settings
    )
    return KnowledgeServices(
        list_entries=ListEntries(uow_factory=uow_factory, search=search),
        create_entry=CreateEntry(
            uow_factory=uow_factory, clock=deps.clock, indexer=indexer
        ),
        get_entry=GetEntry(uow_factory=uow_factory),
        update_entry=UpdateEntry(
            uow_factory=uow_factory, clock=deps.clock, indexer=indexer
        ),
        delete_entry=DeleteEntry(uow_factory=uow_factory),
        search_entries=search,
        public=make_search_port(search, default_limit=settings.default_limit),
    )


def make_search_port(
    search: SearchEntries, *, default_limit: int
) -> KnowledgeSearchPort:
    """The `KnowledgeSearchPort` implementation other modules consume."""
    return KnowledgeSearch(search=search, default_limit=default_limit)


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlKnowledgeUnitOfWork:
        return SqlKnowledgeUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
