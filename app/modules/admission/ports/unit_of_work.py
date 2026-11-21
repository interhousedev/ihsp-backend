"""Port: one transaction over the admission tables, with outbox and audit."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.admission.ports.career import CareerRepository
from app.modules.admission.ports.catalog_proposals import CatalogProposalRepository
from app.modules.admission.ports.catalog_staff import CatalogStaffRepository
from app.modules.admission.ports.chooser import CatalogRepository, ListRepository
from app.modules.admission.ports.consultations import (
    ConsultationRepository,
    ProfileDetailsRepository,
)
from app.modules.admission.ports.documents import (
    ChecklistRepository,
    DeadlineRepository,
    DocumentRepository,
    TranscriptRepository,
)
from app.modules.admission.ports.essay_flow import (
    GalleryRepository,
    GroupLabelRepository,
    IdeaFitCache,
    PracticeRepository,
    PromptCatalog,
    ShortAnswerRepository,
    SlotRepository,
)
from app.modules.admission.ports.essay_invites import (
    EssayFeedbackRepository,
    EssayInviteRepository,
)
from app.modules.admission.ports.essay_reviews import EssayReviewRepository
from app.modules.admission.ports.essays import EssayRepository
from app.modules.admission.ports.exemplars import ExemplarRepository
from app.modules.admission.ports.fit import (
    FitPreferenceRepository,
    ProfessionPlanRepository,
)
from app.modules.admission.ports.goal_plan import GoalRepository
from app.modules.admission.ports.help_proofs import HelpProofsRepository
from app.modules.admission.ports.items import ItemRepository
from app.modules.admission.ports.matching import (
    DecisionRepository,
    PreferenceRepository,
)
from app.modules.admission.ports.memory_notes import MemoryNoteRepository
from app.modules.admission.ports.opp_social import (
    OppCommentRepository,
    OrgRepository,
)
from app.modules.admission.ports.opportunities import OpportunityRepository
from app.modules.admission.ports.outcomes import OutcomeRepository
from app.modules.admission.ports.profile import ProfileRepository, ReviewRepository
from app.modules.admission.ports.repositories import (
    AccessRepository,
    CourseRepository,
    RuntimeSettingsRepository,
)
from app.modules.admission.ports.staff import (
    CommentRepository,
    PrivacyRepository,
    StaffRepository,
)
from app.modules.admission.ports.supp_prompts import SuppPromptRepository
from app.modules.admission.ports.tasks import TaskRepository
from app.modules.admission.ports.test_scores import ScoreRepository
from app.modules.admission.ports.today import TodayRepository
from app.shared.notifications import NotificationDraft


class AdmissionUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() commits it and the outbox."""

    @property
    def access(self) -> AccessRepository:
        """Entitlements, assignments, help grants and the audit log."""
        ...

    @property
    def catalog(self) -> CatalogRepository:
        """Institutions, facts and scholarships."""
        ...

    @property
    def catalog_proposals(self) -> CatalogProposalRepository:
        """Staff proposals to change the catalog."""
        ...

    @property
    def catalog_staff(self) -> CatalogStaffRepository:
        """Staff lists and deletes of institutions and opportunities."""
        ...

    @property
    def opportunities(self) -> OpportunityRepository:
        """Opportunities catalog, submissions and student plans."""
        ...

    @property
    def orgs(self) -> OrgRepository:
        """Organizations behind opportunities."""
        ...

    @property
    def opp_comments(self) -> OppCommentRepository:
        """Comments under opportunities and their reports."""
        ...

    @property
    def shortlist(self) -> ListRepository:
        """A student's university list and affordability checks."""
        ...

    @property
    def courses(self) -> CourseRepository:
        """Stored course rows."""
        ...

    @property
    def runtime_settings(self) -> RuntimeSettingsRepository:
        """Admin-edited settings."""
        ...

    @property
    def profiles(self) -> ProfileRepository:
        """Profiles and the three words."""
        ...

    @property
    def reviews(self) -> ReviewRepository:
        """Cached AI reviews."""
        ...

    @property
    def items(self) -> ItemRepository:
        """Activities, honors, metrics, interviews and item reviews."""
        ...

    @property
    def goals(self) -> GoalRepository:
        """Goal-plan milestones."""
        ...

    @property
    def career(self) -> CareerRepository:
        """Career inventory, majors taxonomy and career plans."""
        ...

    @property
    def essays(self) -> EssayRepository:
        """Essays, versions and the ideas board."""
        ...

    @property
    def essay_reviews(self) -> EssayReviewRepository:
        """Stored base and per-university essay reviews."""
        ...

    @property
    def essay_invites(self) -> EssayInviteRepository:
        """Review links a student shares for an essay."""
        ...

    @property
    def essay_feedback(self) -> EssayFeedbackRepository:
        """Comments that reviewers and the student leave on an essay."""
        ...

    @property
    def exemplars(self) -> ExemplarRepository:
        """The library of published essays of admitted students."""
        ...

    @property
    def tasks(self) -> TaskRepository:
        """Student tasks with steps and links."""
        ...

    @property
    def test_scores(self) -> ScoreRepository:
        """Test catalog and students' test entries."""
        ...

    @property
    def today(self) -> TodayRepository:
        """Activity days (the streak) and the season override."""
        ...

    @property
    def fit_preferences(self) -> FitPreferenceRepository:
        """Fit preference ratings."""
        ...

    @property
    def profession_plans(self) -> ProfessionPlanRepository:
        """Ranked professions and ikigai chips."""
        ...

    @property
    def preferences(self) -> PreferenceRepository:
        """Stored preference answers."""
        ...

    @property
    def decisions(self) -> DecisionRepository:
        """Stored university decisions."""
        ...

    @property
    def outcomes(self) -> OutcomeRepository:
        """Self-reported application outcomes."""
        ...

    @property
    def help_proofs(self) -> HelpProofsRepository:
        """Proofs, help requests and guest links."""
        ...

    @property
    def documents(self) -> DocumentRepository:
        """Documents, versions and attachments."""
        ...

    @property
    def checklist(self) -> ChecklistRepository:
        """A student's checklist."""
        ...

    @property
    def deadlines(self) -> DeadlineRepository:
        """Deadlines, milestones and reminders."""
        ...

    @property
    def transcripts(self) -> TranscriptRepository:
        """Transcript requests and officer settings."""
        ...

    async def cancel_notification(self, dedupe_key: str) -> bool:
        """Cancel a still-pending notification; False when it was claimed."""
        ...

    @property
    def staff(self) -> StaffRepository:
        """Assignments, saved views and the caseload."""
        ...

    @property
    def comments(self) -> CommentRepository:
        """Comments on a student's objects."""
        ...

    @property
    def privacy(self) -> PrivacyRepository:
        """Export, erasure and the audit view."""
        ...

    @property
    def consultations(self) -> ConsultationRepository:
        """Consultation requests."""
        ...

    @property
    def profile_details(self) -> ProfileDetailsRepository:
        """Interests and quiz answers."""
        ...

    @property
    def memory_notes(self) -> MemoryNoteRepository:
        """Memory notes of the student's AI agent."""
        ...

    @property
    def supp_prompts(self) -> SuppPromptRepository:
        """Supplemental essay prompts per institution and cycle."""
        ...

    @property
    def prompt_catalog(self) -> PromptCatalog:
        """Common App and supplemental prompts for the prompt map."""
        ...

    @property
    def practice(self) -> PracticeRepository:
        """Daily practice entries."""
        ...

    @property
    def gallery(self) -> GalleryRepository:
        """Essay versions published to other students."""
        ...

    @property
    def group_labels(self) -> GroupLabelRepository:
        """Generated names of prompt groups."""
        ...

    @property
    def idea_fits(self) -> IdeaFitCache:
        """Cached idea fits."""
        ...

    @property
    def slots(self) -> SlotRepository:
        """Essays placed into the prompt slots of universities."""
        ...

    @property
    def short_answers(self) -> ShortAnswerRepository:
        """Sealed short texts per supplemental prompt."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications to insert at commit."""
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
        """Roll back unless committed."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


UowFactory = Callable[[], AdmissionUnitOfWork]
