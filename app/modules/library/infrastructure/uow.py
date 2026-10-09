"""SQL unit of work of the library module."""

from app.modules.library.infrastructure.repositories.annotation_repository import (
    SqlAnnotationRepository,
)
from app.modules.library.infrastructure.repositories.external_repository import (
    SqlExternalRepository,
)
from app.modules.library.infrastructure.repositories.item_repository import (
    SqlEventRepository,
    SqlItemRepository,
)
from app.modules.library.infrastructure.repositories.moderation_repository import (
    SqlModerationRepository,
)
from app.modules.library.infrastructure.repositories.page_repository import (
    SqlPageRepository,
)
from app.modules.library.infrastructure.repositories.plan_repository import (
    SqlPlanRepository,
)
from app.modules.library.infrastructure.repositories.progress_repository import (
    SqlProgressRepository,
)
from app.modules.library.infrastructure.repositories.reading_list_repository import (
    SqlReadingListRepository,
)
from app.modules.library.infrastructure.repositories.shelf_repository import (
    SqlShelfRepository,
)
from app.modules.library.infrastructure.repositories.stats_repository import (
    SqlStatsRepository,
)
from app.modules.library.infrastructure.repositories.taxonomy_repository import (
    SqlTaxonomyRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class LibrarySqlUnitOfWork(SqlUnitOfWork):
    """One transaction with every library repository, outbox and audit."""

    items: SqlItemRepository
    events: SqlEventRepository
    pages: SqlPageRepository
    taxonomy: SqlTaxonomyRepository
    lists: SqlReadingListRepository
    stats: SqlStatsRepository
    moderation: SqlModerationRepository
    shelf: SqlShelfRepository
    progress: SqlProgressRepository
    annotations: SqlAnnotationRepository
    plans: SqlPlanRepository
    external: SqlExternalRepository

    def _init_repos(self) -> None:
        """Create the repositories bound to the session."""
        session = self.session
        self.items = SqlItemRepository(session)
        self.events = SqlEventRepository(session)
        self.pages = SqlPageRepository(session)
        self.taxonomy = SqlTaxonomyRepository(session)
        self.lists = SqlReadingListRepository(session)
        self.stats = SqlStatsRepository(session)
        self.moderation = SqlModerationRepository(session)
        self.shelf = SqlShelfRepository(session)
        self.progress = SqlProgressRepository(session)
        self.annotations = SqlAnnotationRepository(session)
        self.plans = SqlPlanRepository(session)
        self.external = SqlExternalRepository(session)
