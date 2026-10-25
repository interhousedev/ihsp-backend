"""SQL unit of work of the notebooks module."""

from app.modules.notebooks.infrastructure.lms_course_gate import NO_COURSES
from app.modules.notebooks.infrastructure.repositories.artifact_repository import (
    SqlArtifactRepository,
)
from app.modules.notebooks.infrastructure.repositories.default_material_repository import (  # noqa: E501
    SqlDefaultMaterialRepository,
)
from app.modules.notebooks.infrastructure.repositories.document_repository import (
    SqlDocumentRepository,
)
from app.modules.notebooks.infrastructure.repositories.label_repository import (
    SqlLabelRepository,
)
from app.modules.notebooks.infrastructure.repositories.message_repository import (
    SqlMessageRepository,
)
from app.modules.notebooks.infrastructure.repositories.notebook_repository import (
    SqlNotebookRepository,
)
from app.modules.notebooks.infrastructure.repositories.passage_repository import (
    SqlPassageRepository,
)
from app.modules.notebooks.infrastructure.repositories.presentation_plan_repository import (  # noqa: E501
    SqlPresentationPlanRepository,
)
from app.modules.notebooks.infrastructure.repositories.progress_repository import (
    SqlProgressRepository,
)
from app.modules.notebooks.infrastructure.repositories.shared_cache_repository import (
    SqlSharedCacheRepository,
)
from app.modules.notebooks.infrastructure.repositories.source_repository import (
    SqlSourceRepository,
)
from app.modules.notebooks.ports.course_gate import CourseGate
from app.shared.db.uow import (
    AfterCommit,
    AuditWriter,
    OutboxWriter,
    SqlUnitOfWork,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlNotebooksUnitOfWork(SqlUnitOfWork):
    """One transaction over notebooks, sources, passages, messages and outputs."""

    notebooks: SqlNotebookRepository
    sources: SqlSourceRepository
    passages: SqlPassageRepository
    documents: SqlDocumentRepository
    shared: SqlSharedCacheRepository
    messages: SqlMessageRepository
    artifacts: SqlArtifactRepository
    progress: SqlProgressRepository
    labels: SqlLabelRepository
    default_materials: SqlDefaultMaterialRepository
    plans: SqlPresentationPlanRepository

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        outbox_writer: OutboxWriter,
        audit_writer: AuditWriter,
        outbox_committed_hook: AfterCommit | None = None,
        *,
        course_gate: CourseGate = NO_COURSES,
    ) -> None:
        """Store the factories and the course gate (no LMS: no course opens)."""
        super().__init__(
            sessionmaker, outbox_writer, audit_writer, outbox_committed_hook
        )
        self.course_gate = course_gate

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.notebooks = SqlNotebookRepository(self.session)
        self.sources = SqlSourceRepository(self.session)
        self.passages = SqlPassageRepository(self.session)
        self.documents = SqlDocumentRepository(self.session)
        self.shared = SqlSharedCacheRepository(self.session)
        self.messages = SqlMessageRepository(self.session)
        self.artifacts = SqlArtifactRepository(self.session)
        self.progress = SqlProgressRepository(self.session)
        self.labels = SqlLabelRepository(self.session)
        self.default_materials = SqlDefaultMaterialRepository(self.session)
        self.plans = SqlPresentationPlanRepository(self.session)
