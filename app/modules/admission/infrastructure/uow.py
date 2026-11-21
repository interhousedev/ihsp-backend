"""SQL unit of work of the admission module."""

from typing import Any, Self
from uuid import UUID

from app.modules.admission.domain.calendar import TASHKENT
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
from app.modules.admission.infrastructure.essay_flow_repository import (
    SqlGalleryRepository,
    SqlGroupLabelRepository,
    SqlIdeaFitCache,
    SqlPracticeRepository,
    SqlPromptCatalog,
    SqlShortAnswerRepository,
    SqlSlotRepository,
)
from app.modules.admission.infrastructure.essay_invites_repository import (
    SqlEssayFeedbackRepository,
    SqlEssayInviteRepository,
)
from app.modules.admission.infrastructure.essay_reviews_repository import (
    SqlEssayReviewRepository,
)
from app.modules.admission.infrastructure.essays_repository import (
    SqlEssayRepository,
)
from app.modules.admission.infrastructure.exemplars_repository import (
    SqlExemplarRepository,
)
from app.modules.admission.infrastructure.fit_repository import (
    SqlFitPreferenceRepository,
    SqlProfessionPlanRepository,
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
from app.modules.admission.infrastructure.orm.essay_flow import EssayPracticeRow
from app.modules.admission.infrastructure.orm.profile import EssayRow, ItemRow
from app.modules.admission.infrastructure.orm.tasks import TaskRow
from app.modules.admission.infrastructure.orm.test_scores import ScoreEntryRow
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
from app.modules.admission.infrastructure.today_repository import SqlTodayRepository
from app.modules.admission.ports.essay_crypto import EssayCipher
from app.shared.clock import Clock
from app.shared.db.uow import SqlUnitOfWork
from app.shared.notifications import NotificationOutbox

from sqlalchemy import event
from sqlalchemy.orm import Session

_STUDENT_WRITES = (EssayRow, ItemRow, ScoreEntryRow, EssayPracticeRow)
"""Rows whose change is a student's own work (the streak)."""


def _worker(obj: object) -> UUID | None:
    """The student whose work a changed row is, or None when it is not work."""
    if isinstance(obj, TaskRow):
        return obj.student_id if obj.created_by == "student" else None
    if isinstance(obj, _STUDENT_WRITES):
        return obj.student_id
    return None


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
    essay_reviews: SqlEssayReviewRepository
    essay_invites: SqlEssayInviteRepository
    essay_feedback: SqlEssayFeedbackRepository
    exemplars: SqlExemplarRepository
    opportunities: SqlOpportunityRepository
    tasks: SqlTaskRepository
    test_scores: SqlScoreRepository
    today: SqlTodayRepository
    fit_preferences: SqlFitPreferenceRepository
    profession_plans: SqlProfessionPlanRepository
    preferences: SqlPreferenceRepository
    decisions: SqlDecisionRepository
    outcomes: SqlOutcomeRepository
    consultations: SqlConsultationRepository
    profile_details: SqlProfileDetailsRepository
    memory_notes: SqlMemoryNoteRepository
    supp_prompts: SqlSuppPromptRepository
    prompt_catalog: SqlPromptCatalog
    practice: SqlPracticeRepository
    gallery: SqlGalleryRepository
    slots: SqlSlotRepository
    short_answers: SqlShortAnswerRepository
    group_labels: SqlGroupLabelRepository
    idea_fits: SqlIdeaFitCache

    def __init__(
        self,
        *args: Any,
        cipher: EssayCipher,
        clock: Clock,
        notification_outbox: NotificationOutbox | None = None,
        **kwargs: Any,
    ) -> None:
        """Keep the essay cipher, the clock and the outbox that can cancel."""
        super().__init__(*args, **kwargs)
        self._cipher = cipher
        self._clock = clock
        self._notification_outbox = notification_outbox

    async def __aenter__(self) -> Self:
        """Open the transaction and watch the rows that count toward the streak."""
        await super().__aenter__()
        self._active: set[UUID] = set()
        event.listen(self.session.sync_session, "after_flush", self._on_flush)
        return self

    def _on_flush(self, session: Session, _context: object) -> None:
        changed = (
            *session.new,
            *(o for o in session.dirty if session.is_modified(o)),
            *session.deleted,
        )
        self._active.update(w for w in map(_worker, changed) if w is not None)

    async def commit(self) -> None:
        """Record today as an active day of every student who worked, then commit."""
        if self._active:
            await self.today.touch(
                self._active, self._clock.now().astimezone(TASHKENT).date()
            )
            self._active = set()
        await super().commit()

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
        self.privacy = SqlPrivacyRepository(self.session, self._cipher)
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
        self.essays = SqlEssayRepository(self.session, self._cipher)
        self.essay_reviews = SqlEssayReviewRepository(self.session, self._cipher)
        self.essay_invites = SqlEssayInviteRepository(self.session, self._cipher)
        self.essay_feedback = SqlEssayFeedbackRepository(self.session, self._cipher)
        self.exemplars = SqlExemplarRepository(self.session)
        self.opportunities = SqlOpportunityRepository(self.session)
        self.tasks = SqlTaskRepository(self.session)
        self.test_scores = SqlScoreRepository(self.session)
        self.today = SqlTodayRepository(self.session)
        self.fit_preferences = SqlFitPreferenceRepository(self.session)
        self.profession_plans = SqlProfessionPlanRepository(self.session)
        self.preferences = SqlPreferenceRepository(self.session)
        self.decisions = SqlDecisionRepository(self.session)
        self.outcomes = SqlOutcomeRepository(self.session)
        self.consultations = SqlConsultationRepository(self.session)
        self.profile_details = SqlProfileDetailsRepository(self.session)
        self.memory_notes = SqlMemoryNoteRepository(self.session)
        self.supp_prompts = SqlSuppPromptRepository(self.session)
        self.prompt_catalog = SqlPromptCatalog(self.session)
        self.practice = SqlPracticeRepository(self.session, self._cipher)
        self.gallery = SqlGalleryRepository(self.session)
        self.slots = SqlSlotRepository(self.session)
        self.short_answers = SqlShortAnswerRepository(self.session, self._cipher)
        self.group_labels = SqlGroupLabelRepository(self.session)
        self.idea_fits = SqlIdeaFitCache(self.session)

    async def cancel_notification(self, dedupe_key: str) -> bool:
        """Cancel a still-pending notification; False when it was claimed."""
        if self._notification_outbox is None:
            return False
        return await self._notification_outbox.cancel_pending(self.session, dedupe_key)
