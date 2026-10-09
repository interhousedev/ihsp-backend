"""Port: one transaction over the library repositories, outbox and audit."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.library.ports.annotation_repository import AnnotationRepository
from app.modules.library.ports.external_repository import ExternalRepository
from app.modules.library.ports.item_repository import EventRepository, ItemRepository
from app.modules.library.ports.moderation_repository import ModerationRepository
from app.modules.library.ports.page_repository import PageRepository
from app.modules.library.ports.plan_repository import PlanRepository
from app.modules.library.ports.progress_repository import ProgressRepository
from app.modules.library.ports.reading_list_repository import ReadingListRepository
from app.modules.library.ports.shelf_repository import ShelfRepository
from app.modules.library.ports.stats_repository import StatsRepository
from app.modules.library.ports.taxonomy_repository import TaxonomyRepository
from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft


class LibraryUnitOfWork(Protocol):
    """Opens a transaction on entry; `commit()` writes outbox and audit, commits."""

    @property
    def items(self) -> ItemRepository:
        """Items, their details, files and tags."""
        ...

    @property
    def events(self) -> EventRepository:
        """History of items."""
        ...

    @property
    def pages(self) -> PageRepository:
        """Indexed text pages."""
        ...

    @property
    def taxonomy(self) -> TaxonomyRepository:
        """Topics and collections."""
        ...

    @property
    def lists(self) -> ReadingListRepository:
        """Reading lists."""
        ...

    @property
    def stats(self) -> StatsRepository:
        """Daily statistics."""
        ...

    @property
    def moderation(self) -> ModerationRepository:
        """Reports, sanctions, suggestions, queue."""
        ...

    @property
    def shelf(self) -> ShelfRepository:
        """Shelves."""
        ...

    @property
    def progress(self) -> ProgressRepository:
        """Reading progress."""
        ...

    @property
    def annotations(self) -> AnnotationRepository:
        """Annotations."""
        ...

    @property
    def plans(self) -> PlanRepository:
        """Book plans and lesson links."""
        ...

    @property
    def external(self) -> ExternalRepository:
        """External records beyond the item itself."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed, then close."""
        ...

    async def commit(self) -> None:
        """Write the outbox and audit rows, commit, then run the hooks."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications for the outbox."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        ...

    def after_commit(self, hook: AfterCommit) -> None:
        """Run a coroutine after a successful commit (e.g. kick a task)."""
        ...


UowFactory = Callable[[], LibraryUnitOfWork]
