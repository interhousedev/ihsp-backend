"""SQL unit of work of the admission module."""

from typing import Any

from app.modules.admission.infrastructure.career_repository import (
    SqlCareerRepository,
)
from app.modules.admission.infrastructure.catalog_proposals_repository import (
    SqlCatalogProposalRepository,
)
from app.modules.admission.infrastructure.chooser_repositories import (
    SqlCatalogRepository,
    SqlListRepository,
)
from app.modules.admission.infrastructure.consult_repository import (
    SqlConsultationRepository,
    SqlProfileDetailsRepository,
)
from app.modules.admission.infrastructure.documents_repositories import (
    SqlChecklistRepository,
    SqlDeadlineRepository,
    SqlDocumentRepository,
    SqlTranscriptRepository,
)
from app.modules.admission.infrastructure.essays_repository import (
    SqlEssayRepository,
)
from app.modules.admission.infrastructure.goal_plan_repository import (
    SqlGoalRepository,
)
from app.modules.admission.infrastructure.help_proofs_repo import (
    SqlHelpProofsRepository,
)
from app.modules.admission.infrastructure.items_repository import SqlItemRepository
from app.modules.admission.infrastructure.matching_repository import (
    SqlDecisionRepository,
    SqlPreferenceRepository,
)
from app.modules.admission.infrastructure.memory_notes_repository import (
    SqlMemoryNoteRepository,
)
from app.modules.admission.infrastructure.opp_social_repository import (
    SqlOppCommentRepository,
    SqlOrgRepository,
)
from app.modules.admission.infrastructure.opportunities_repository import (
    SqlOpportunityRepository,
)
from app.modules.admission.infrastructure.outcomes_repository import (
    SqlOutcomeRepository,
)
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
from app.modules.admission.infrastructure.supp_prompts_repository import (
    SqlSuppPromptRepository,
)
from app.modules.admission.infrastructure.tasks_repository import SqlTaskRepository
from app.modules.admission.infrastructure.test_scores_repository import (
    SqlScoreRepository,
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
    orgs: SqlOrgRepository
    opp_comments: SqlOppCommentRepository
    help_proofs: SqlHelpProofsRepository
    documents: SqlDocumentRepository
    checklist: SqlChecklistRepository
    deadlines: SqlDeadlineRepository
    transcripts: SqlTranscriptRepository
    items: SqlItemRepository
    goals: SqlGoalRepository
    career: SqlCareerRepository
    essays: SqlEssayRepository
    opportunities: SqlOpportunityRepository
    tasks: SqlTaskRepository
    test_scores: SqlScoreRepository
    preferences: SqlPreferenceRepository
    decisions: SqlDecisionRepository
    outcomes: SqlOutcomeRepository
    consultations: SqlConsultationRepository
    profile_details: SqlProfileDetailsRepository
    memory_notes: SqlMemoryNoteRepository
    supp_prompts: SqlSuppPromptRepository

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
        self.orgs = SqlOrgRepository(self.session)
        self.opp_comments = SqlOppCommentRepository(self.session)
        self.help_proofs = SqlHelpProofsRepository(self.session)
        self.documents = SqlDocumentRepository(self.session)
        self.checklist = SqlChecklistRepository(self.session)
        self.deadlines = SqlDeadlineRepository(self.session)
        self.transcripts = SqlTranscriptRepository(self.session)
        self.items = SqlItemRepository(self.session)
        self.goals = SqlGoalRepository(self.session)
        self.career = SqlCareerRepository(self.session)
        self.essays = SqlEssayRepository(self.session)
        self.opportunities = SqlOpportunityRepository(self.session)
        self.tasks = SqlTaskRepository(self.session)
        self.test_scores = SqlScoreRepository(self.session)
        self.preferences = SqlPreferenceRepository(self.session)
        self.decisions = SqlDecisionRepository(self.session)
        self.outcomes = SqlOutcomeRepository(self.session)
        self.consultations = SqlConsultationRepository(self.session)
        self.profile_details = SqlProfileDetailsRepository(self.session)
        self.memory_notes = SqlMemoryNoteRepository(self.session)
        self.supp_prompts = SqlSuppPromptRepository(self.session)

    async def cancel_notification(self, dedupe_key: str) -> bool:
        """Cancel a still-pending notification; False when it was claimed."""
        if self._notification_outbox is None:
            return False
        return await self._notification_outbox.cancel_pending(self.session, dedupe_key)
