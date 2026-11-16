"""SQL unit of work of the admission module."""

from typing import Any

from app.modules.admission.infrastructure.catalog_proposals_repository import (
    SqlCatalogProposalRepository,
)
from app.modules.admission.infrastructure.chooser_repositories import (
    SqlCatalogRepository,
    SqlListRepository,
)
from app.modules.admission.infrastructure.documents_repositories import (
    SqlChecklistRepository,
    SqlDeadlineRepository,
    SqlDocumentRepository,
    SqlTranscriptRepository,
)
from app.modules.admission.infrastructure.goal_plan_repository import (
    SqlGoalRepository,
)
from app.modules.admission.infrastructure.help_proofs_repo import (
    SqlHelpProofsRepository,
)
from app.modules.admission.infrastructure.items_repository import SqlItemRepository
from app.modules.admission.infrastructure.profile_repositories import (
    SqlProfileRepository,
    SqlReviewRepository,
)
from app.modules.admission.infrastructure.repositories import (
    SqlAccessRepository,
    SqlCourseRepository,
    SqlRuntimeSettingsRepository,
)
from app.modules.admission.infrastructure.staff_repositories import (
    SqlCommentRepository,
    SqlPrivacyRepository,
    SqlStaffRepository,
)
from app.shared.db.uow import SqlUnitOfWork
from app.shared.notifications import NotificationOutbox


class SqlAdmissionUnitOfWork(SqlUnitOfWork):
    """One transaction over the admission tables."""

    access: SqlAccessRepository
    catalog: SqlCatalogRepository
    catalog_proposals: SqlCatalogProposalRepository
    shortlist: SqlListRepository
    courses: SqlCourseRepository
    runtime_settings: SqlRuntimeSettingsRepository
    profiles: SqlProfileRepository
    reviews: SqlReviewRepository
    staff: SqlStaffRepository
    comments: SqlCommentRepository
    privacy: SqlPrivacyRepository
    help_proofs: SqlHelpProofsRepository
    documents: SqlDocumentRepository
    checklist: SqlChecklistRepository
    deadlines: SqlDeadlineRepository
    transcripts: SqlTranscriptRepository
    items: SqlItemRepository
    goals: SqlGoalRepository

    def __init__(
        self,
        *args: Any,
        notification_outbox: NotificationOutbox | None = None,
        **kwargs: Any,
    ) -> None:
        """Keep the outbox that can cancel pending notifications."""
        super().__init__(*args, **kwargs)
        self._notification_outbox = notification_outbox

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.access = SqlAccessRepository(self.session)
        self.catalog = SqlCatalogRepository(self.session)
        self.catalog_proposals = SqlCatalogProposalRepository(self.session)
        self.shortlist = SqlListRepository(self.session)
        self.courses = SqlCourseRepository(self.session)
        self.runtime_settings = SqlRuntimeSettingsRepository(self.session)
        self.profiles = SqlProfileRepository(self.session)
        self.reviews = SqlReviewRepository(self.session)
        self.staff = SqlStaffRepository(self.session)
        self.comments = SqlCommentRepository(self.session)
        self.privacy = SqlPrivacyRepository(self.session)
        self.help_proofs = SqlHelpProofsRepository(self.session)
        self.documents = SqlDocumentRepository(self.session)
        self.checklist = SqlChecklistRepository(self.session)
        self.deadlines = SqlDeadlineRepository(self.session)
        self.transcripts = SqlTranscriptRepository(self.session)
        self.items = SqlItemRepository(self.session)
        self.goals = SqlGoalRepository(self.session)

    async def cancel_notification(self, dedupe_key: str) -> bool:
        """Cancel a still-pending notification; False when it was claimed."""
        if self._notification_outbox is None:
            return False
        return await self._notification_outbox.cancel_pending(self.session, dedupe_key)
