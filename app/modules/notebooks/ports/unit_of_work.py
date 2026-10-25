"""Port: one transaction over the notebooks repositories."""

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.notebooks.ports.artifact_repository import (
    ArtifactRepository,
    ProgressRepository,
)
from app.modules.notebooks.ports.course_gate import CourseGate
from app.modules.notebooks.ports.default_material_repository import (
    DefaultMaterialRepository,
)
from app.modules.notebooks.ports.document_repository import DocumentRepository
from app.modules.notebooks.ports.label_repository import LabelRepository
from app.modules.notebooks.ports.message_repository import MessageRepository
from app.modules.notebooks.ports.notebook_repository import NotebookRepository
from app.modules.notebooks.ports.passage_repository import PassageRepository
from app.modules.notebooks.ports.presentation_plan_repository import (
    PresentationPlanRepository,
)
from app.modules.notebooks.ports.shared_cache_repository import SharedCacheRepository
from app.modules.notebooks.ports.source_repository import SourceRepository
from app.shared.notifications import NotificationDraft


class NotebooksUnitOfWork(Protocol):
    """Opens a transaction on entry; `commit()` commits, then runs the hooks."""

    @property
    def notebooks(self) -> NotebookRepository:
        """Notebooks of the open transaction."""
        ...

    @property
    def sources(self) -> SourceRepository:
        """Sources."""
        ...

    @property
    def passages(self) -> PassageRepository:
        """Passages (read through the sources)."""
        ...

    @property
    def documents(self) -> DocumentRepository:
        """The shared texts, their passages, aliases and guides."""
        ...

    @property
    def shared(self) -> SharedCacheRepository:
        """The shared summary and Studio output caches."""
        ...

    @property
    def messages(self) -> MessageRepository:
        """Chat messages."""
        ...

    @property
    def artifacts(self) -> ArtifactRepository:
        """Studio outputs."""
        ...

    @property
    def progress(self) -> ProgressRepository:
        """Progress in flash card decks and quizzes."""
        ...

    @property
    def labels(self) -> LabelRepository:
        """Topic labels of sources and the state of the auto labeling."""
        ...

    @property
    def course_gate(self) -> CourseGate:
        """Course permissions for the shared workspace of an LMS course."""
        ...

    @property
    def default_materials(self) -> DefaultMaterialRepository:
        """Default materials of EMIS subject ids (copied into subject notebooks)."""
        ...

    @property
    def plans(self) -> PresentationPlanRepository:
        """Slide outlines confirmed before a deck is generated."""
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

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications (the bell) to insert with the commit."""
        ...

    def after_commit(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Run a coroutine after a successful commit (e.g. kick a task)."""
        ...

    async def commit(self) -> None:
        """Commit the transaction and run the after-commit hooks."""
        ...


UowFactory = Callable[[], NotebooksUnitOfWork]
