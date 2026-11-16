"""Builds the admission module (container.admission)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import ResolveAdmissionActor
from app.modules.admission.application.catalog_proposals import (
    CatalogProposalService,
)
from app.modules.admission.application.catalog_research import CatalogResearch
from app.modules.admission.application.chooser import CatalogService, ListService
from app.modules.admission.application.comments import CommentService
from app.modules.admission.application.config import GetConfig
from app.modules.admission.application.courses import CourseService
from app.modules.admission.application.deadlines import DeadlineService
from app.modules.admission.application.documents import DocumentService
from app.modules.admission.application.goal_plan import GoalPlanService
from app.modules.admission.application.goal_plan_suggest import GoalPlanSuggester
from app.modules.admission.application.guest import GuestService
from app.modules.admission.application.help import HelpService
from app.modules.admission.application.interview import ItemInterviewService
from app.modules.admission.application.items import ItemService
from app.modules.admission.application.privacy import PrivacyService
from app.modules.admission.application.profile import ProfileService
from app.modules.admission.application.profile_alignment import AlignmentService
from app.modules.admission.application.proofs import ProofService
from app.modules.admission.application.review import ItemReviewService
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.application.staff import StaffService
from app.modules.admission.application.transcripts import TranscriptService
from app.modules.admission.application.words import WordsService
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.uow import SqlAdmissionUnitOfWork
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.consent import (
    MemoryPurposeConsents,
    PurposeConsentStore,
)
from app.modules.admission.ports.courses import CourseSources
from app.modules.admission.ports.staff import StaffDirectory
from app.modules.admission.ports.unit_of_work import UowFactory
from app.modules.notebooks.application.llm import NotebookLlm
from app.shared.contracts.academic import AcademicMembership
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


class UnavailableAi:
    """Stands in when no model is configured; every call fails clearly."""

    async def json(self, **_: object) -> tuple[dict[str, object], str]:
        """Refuse: the AI is not built in this process."""
        raise RuntimeError("admission AI is not configured")


@dataclass(slots=True)
class AdmissionServices:
    """Use cases of the admission module.

    Every route resolves `actor` first, then goes through `access` for any read or
    write of a student's data. `uow_factory` is for later slices of this module.
    """

    actor: ResolveAdmissionActor
    access: AccessPolicy
    runtime: RuntimeSettingsService
    config: GetConfig
    courses: CourseService
    staff: StaffService
    comments: CommentService
    privacy: PrivacyService
    catalog: CatalogService
    catalog_proposals: CatalogProposalService
    chooser: ListService
    catalog_research: CatalogResearch | None
    uow_factory: UowFactory
    profile: ProfileService
    words: WordsService
    alignment: AlignmentService
    proofs: ProofService
    help: HelpService
    guest: GuestService
    documents: DocumentService
    transcripts: TranscriptService
    deadlines: DeadlineService
    items: ItemService
    goal_plan: GoalPlanService
    goal_plan_suggest: GoalPlanSuggester
    item_reviews: ItemReviewService
    item_interviews: ItemInterviewService


@dataclass(frozen=True, slots=True)
class AdmissionOverrides:
    """Replacement for the SQL unit of work (for tests)."""

    uow_factory: UowFactory | None = None


def build(
    deps: ModuleDeps,
    *,
    membership: AcademicMembership,
    course_sources: CourseSources,
    purpose_consents: PurposeConsentStore | None = None,
    staff_directory: StaffDirectory | None = None,
    ai: StructuredAi | None = None,
    overrides: AdmissionOverrides | None = None,
    llm: NotebookLlm | None = None,
    files: FilesApi | None = None,
    identity: IdentityDirectory | None = None,
    prompts: PromptSource | None = None,
) -> AdmissionServices:
    """Wire the module; without `purpose_consents` they live in process memory."""
    over = overrides or AdmissionOverrides()
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    settings = deps.settings.admission
    grades = settings.eligible_grades
    consents = purpose_consents or MemoryPurposeConsents()
    access = AccessPolicy(
        uow_factory,
        membership,
        consents,
        deps.clock,
        grades,
    )
    runtime = RuntimeSettingsService(uow_factory, ttl=settings.runtime_cache_seconds)
    model = ai or UnavailableAi()
    texts = prompts or BuiltinPrompts()
    limits = deps.effective_limits
    return AdmissionServices(
        actor=ResolveAdmissionActor(uow_factory, membership, deps.clock, grades),
        access=access,
        runtime=runtime,
        config=GetConfig(settings, runtime, limits),
        courses=CourseService(uow_factory, access, course_sources),
        staff=StaffService(
            uow_factory, access, membership, staff_directory, deps.clock, identity
        ),
        comments=CommentService(uow_factory, access, deps.clock, identity),
        privacy=PrivacyService(uow_factory, consents, deps.clock),
        catalog=CatalogService(uow_factory),
        catalog_proposals=CatalogProposalService(uow_factory, deps.clock),
        chooser=ListService(
            uow_factory, access, runtime, settings, deps.clock, identity
        ),
        catalog_research=CatalogResearch(uow_factory, llm, texts) if llm else None,
        uow_factory=uow_factory,
        profile=ProfileService(uow_factory, access, runtime, deps.clock),
        words=WordsService(uow_factory, access, model, consents, deps.clock, texts),
        alignment=AlignmentService(
            uow_factory,
            access,
            model,
            consents,
            deps.clock,
            _quota_of(deps, "admit_alignment_map_per_week"),
            texts,
        ),
        proofs=ProofService(
            uow_factory,
            access,
            deps.clock,
            deps.rate_limiter,
            _quota_of(deps, "admit_proof_check_per_day"),
            files,
        ),
        help=HelpService(uow_factory, access, deps.clock, deps.rate_limiter),
        guest=GuestService(
            uow_factory,
            access,
            deps.clock,
            deps.rate_limiter,
            default_days=settings.guest_links.ttl_days,
            default_sessions=settings.guest_links.max_sessions,
            max_active=settings.guest_links.max_active_per_student,
            identity=identity,
        ),
        documents=DocumentService(uow_factory, access, deps.clock, files, identity),
        transcripts=TranscriptService(
            uow_factory, access, runtime, deps.clock, membership, files, identity
        ),
        deadlines=DeadlineService(uow_factory, access, deps.clock),
        items=ItemService(uow_factory, access),
        goal_plan=GoalPlanService(uow_factory, access, deps.clock),
        goal_plan_suggest=GoalPlanSuggester(
            uow_factory,
            access,
            model,
            consents,
            deps.clock,
            deps.rate_limiter,
            _quota_of(deps, "admit_goal_plan_per_week"),
            texts,
        ),
        item_reviews=ItemReviewService(
            uow_factory,
            access,
            model,
            deps.clock,
            texts,
            per_day=_quota_of(deps, "admit_item_review_per_day"),
        ),
        item_interviews=ItemInterviewService(uow_factory, access, model, texts),
    )


def _quota_of(deps: ModuleDeps, name: str) -> QuotaOf:
    """Read a soft limit at call time, so a change on the admin page applies."""

    async def read(user_id: UUID) -> int | None:
        value = getattr(await deps.effective_limits.for_user(user_id), name)
        return None if value is None else int(value)

    return read


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    """Return a factory of SQL units of work on the shared sessionmaker."""

    def factory() -> SqlAdmissionUnitOfWork:
        return SqlAdmissionUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
            notification_outbox=deps.notification_outbox,
        )

    return factory
