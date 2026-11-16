"""Builds the admission module (container.admission)."""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import ResolveAdmissionActor
from app.modules.admission.application.app_review import AppReviewService
from app.modules.admission.application.app_review_inputs import UowReviewInputs
from app.modules.admission.application.assistant import AssistantService
from app.modules.admission.application.calendar import (
    CalendarService,
    OpportunitySource,
    ScoreCalendarSource,
)
from app.modules.admission.application.career import CareerService
from app.modules.admission.application.career_suggest import CareerSuggester
from app.modules.admission.application.catalog_proposals import (
    CatalogProposalService,
)
from app.modules.admission.application.catalog_research import CatalogResearch
from app.modules.admission.application.chances import ChancesService
from app.modules.admission.application.chooser import CatalogService, ListService
from app.modules.admission.application.comments import CommentService
from app.modules.admission.application.config import GetConfig
from app.modules.admission.application.courses import CourseService
from app.modules.admission.application.deadlines import DeadlineService
from app.modules.admission.application.documents import DocumentService
from app.modules.admission.application.essays import (
    EssayCoach,
    EssayService,
    UowEssayReader,
)
from app.modules.admission.application.goal_plan import GoalPlanService
from app.modules.admission.application.goal_plan_suggest import GoalPlanSuggester
from app.modules.admission.application.guest import GuestService
from app.modules.admission.application.help import HelpService
from app.modules.admission.application.interview import ItemInterviewService
from app.modules.admission.application.items import ItemService
from app.modules.admission.application.list_plan import ListPlanService
from app.modules.admission.application.matching import MatchService
from app.modules.admission.application.mentoring import MentoringService
from app.modules.admission.application.opportunities import (
    LmsCourseLookup,
    OpportunityService,
)
from app.modules.admission.application.opportunity_intake import OpportunityIntake
from app.modules.admission.application.opportunity_planner import OpportunityPlanner
from app.modules.admission.application.privacy import Eraser, PrivacyService
from app.modules.admission.application.profile import ProfileService
from app.modules.admission.application.profile_alignment import AlignmentService
from app.modules.admission.application.proofs import ProofService
from app.modules.admission.application.readiness import ReadinessService
from app.modules.admission.application.review import ItemReviewService
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.application.staff import StaffService
from app.modules.admission.application.tasks import TaskService
from app.modules.admission.application.tasks_suggest import TaskSuggester
from app.modules.admission.application.test_scores import ScoreService
from app.modules.admission.application.transcripts import TranscriptService
from app.modules.admission.application.voice import VoiceService
from app.modules.admission.application.words import WordsService
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.app_review_repository import (
    SqlAppReviewRepository,
)
from app.modules.admission.infrastructure.assistant_adapters import UowAssistantData
from app.modules.admission.infrastructure.assistant_repository import (
    SqlAssistantRepository,
)
from app.modules.admission.infrastructure.calendar_repository import (
    SqlCalendarStore,
)
from app.modules.admission.infrastructure.catalog_data import study_fields as _fields
from app.modules.admission.infrastructure.uow import SqlAdmissionUnitOfWork
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.assistant import AssistantModel
from app.modules.admission.ports.calendar import CalendarStore
from app.modules.admission.ports.consent import (
    MemoryPurposeConsents,
    PurposeConsentStore,
)
from app.modules.admission.ports.courses import CourseSources
from app.modules.admission.ports.essays import EssayReader
from app.modules.admission.ports.staff import StaffDirectory
from app.modules.admission.ports.student_search import StudentDataHit, StudentDataSearch
from app.modules.admission.ports.unit_of_work import UowFactory
from app.modules.admission.ports.voice import VoiceAi
from app.modules.notebooks.application.llm import NotebookLlm
from app.shared.contracts.academic import AcademicMembership
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.web_search import WebSearchGateway
from app.shared.wiring import ModuleDeps


class UnavailableAi:
    """Stands in when no model is configured; every call fails clearly."""

    async def json(self, **_: object) -> tuple[dict[str, object], str]:
        """Refuse: the AI is not built in this process."""
        raise RuntimeError("admission AI is not configured")


class UnavailableAssistantModel:
    """Stands in when no model is configured."""

    async def turn(self, **_: object) -> dict[str, object]:
        """Refuse: the AI is not built in this process."""
        raise RuntimeError("admission AI is not configured")


class NoStudentSearch:
    """Stands in when no student search is built: it finds nothing."""

    async def search(self, *_: object, **__: object) -> list[StudentDataHit]:
        """No hits."""
        return []

    async def reindex(self, *_: object) -> int:
        """Nothing to index."""
        return 0

    async def forget(self, *_: object) -> None:
        """Nothing to forget."""


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
    mentoring: MentoringService
    catalog: CatalogService
    catalog_proposals: CatalogProposalService
    chooser: ListService
    chances: ChancesService
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
    essays: EssayService
    essay_coach: EssayCoach
    essay_reader: EssayReader
    item_reviews: ItemReviewService
    item_interviews: ItemInterviewService
    opportunity_intake: OpportunityIntake
    opportunities: OpportunityService
    opportunity_planner: OpportunityPlanner
    app_review: AppReviewService
    career: CareerService
    career_ai: CareerSuggester
    voice: VoiceService | None
    list_plan: ListPlanService
    calendar: CalendarService
    tasks: TaskService
    test_scores: ScoreService
    matching: MatchService
    readiness: ReadinessService
    tasks_ai: TaskSuggester
    assistant: AssistantService


@dataclass(frozen=True, slots=True)
class AdmissionOverrides:
    """Replacement for the SQL unit of work (for tests)."""

    uow_factory: UowFactory | None = None
    calendar_store: CalendarStore | None = None


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
    web_search: WebSearchGateway | None = None,
    profile_of: Any = None,
    lms_courses: LmsCourseLookup | None = None,
    voice: VoiceAi | None = None,
    student_search: StudentDataSearch | None = None,
    assistant_model: AssistantModel | None = None,
    erasers: Sequence[Eraser] = (),
    final_erasers: Sequence[Eraser] = (),
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
    assistant_repo = SqlAssistantRepository(deps.sessionmaker)
    limits = deps.effective_limits
    opportunities = OpportunityService(
        uow_factory, access, deps.clock, lms_courses, deps.rate_limiter
    )
    chooser = ListService(uow_factory, access, runtime, settings, deps.clock, identity)
    calendar = CalendarService(
        uow_factory,
        access,
        over.calendar_store or SqlCalendarStore(deps.sessionmaker),
        runtime,
        deps.clock,
        deps.i18n.t,
    )
    calendar.register(OpportunitySource(opportunities.deadlines_for, calendar.store))
    scores = ScoreService(uow_factory, access, deps.clock)
    calendar.register(ScoreCalendarSource(scores.dated, calendar.store, deps.i18n.t))
    list_plan = ListPlanService(
        uow_factory,
        access,
        chooser,
        model,
        consents,
        deps.clock,
        deps.rate_limiter,
        _quota_of(deps, "admit_list_suggest_per_week"),
        texts,
        student_search,
    )
    return AdmissionServices(
        actor=ResolveAdmissionActor(uow_factory, membership, deps.clock, grades),
        access=access,
        runtime=runtime,
        config=GetConfig(settings, runtime, limits, cache(_fields)),
        courses=CourseService(uow_factory, access, course_sources),
        staff=StaffService(
            uow_factory, access, membership, staff_directory, deps.clock, identity
        ),
        comments=CommentService(uow_factory, access, deps.clock, identity),
        mentoring=MentoringService(uow_factory),
        privacy=PrivacyService(
            uow_factory,
            consents,
            deps.clock,
            student_search,
            assistant=assistant_repo,
            erasers=erasers,
            file_remover=files.delete_file if files else None,
            final_erasers=final_erasers,
        ),
        catalog=CatalogService(uow_factory),
        catalog_proposals=CatalogProposalService(uow_factory, deps.clock),
        chooser=chooser,
        chances=ChancesService(uow_factory, runtime, settings),
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
        help=HelpService(
            uow_factory, access, deps.clock, deps.rate_limiter, files, identity
        ),
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
        documents=DocumentService(
            uow_factory, access, deps.clock, files, identity, limits
        ),
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
            student_search,
        ),
        essays=EssayService(uow_factory, access, deps.clock),
        essay_coach=EssayCoach(
            uow_factory,
            access,
            model,
            consents,
            deps.clock,
            deps.rate_limiter,
            _quota_of(deps, "admit_essay_coach_per_day"),
            texts,
            student_search,
        ),
        essay_reader=UowEssayReader(uow_factory),
        item_reviews=ItemReviewService(
            uow_factory,
            access,
            model,
            consents,
            deps.clock,
            texts,
            per_day=_quota_of(deps, "admit_item_review_per_day"),
        ),
        item_interviews=ItemInterviewService(
            uow_factory, access, model, consents, texts
        ),
        opportunity_intake=OpportunityIntake(
            model, texts, web_search=web_search, profile_of=profile_of
        ),
        opportunities=opportunities,
        opportunity_planner=OpportunityPlanner(
            uow_factory,
            access,
            opportunities,
            model,
            consents,
            deps.clock,
            deps.rate_limiter,
            _quota_of(deps, "admit_opportunity_plan_per_week"),
            texts,
        ),
        app_review=AppReviewService(
            SqlAppReviewRepository(deps.sessionmaker),
            UowReviewInputs(uow_factory, UowEssayReader(uow_factory)),
            access,
            model,
            consents,
            deps.clock,
            deps.rate_limiter,
            _quota_of(deps, "admit_app_review_per_week"),
            texts,
            deps.kicker,
            limits,
        ),
        career=CareerService(uow_factory, access, deps.clock),
        career_ai=CareerSuggester(
            uow_factory,
            access,
            model,
            consents,
            deps.rate_limiter,
            _quota_of(deps, "admit_career_ai_per_week"),
            texts,
            student_search,
        ),
        voice=(
            VoiceService(
                uow_factory,
                voice,
                deps.rate_limiter,
                _quota_of(deps, "admit_voice_per_day"),
                limits,
                consents,
            )
            if voice is not None
            else None
        ),
        list_plan=list_plan,
        tasks=TaskService(uow_factory, access, deps.clock),
        test_scores=scores,
        matching=MatchService(uow_factory, chooser, deps.clock),
        readiness=ReadinessService(
            uow_factory, access, runtime, settings.readiness, deps.clock, list_plan
        ),
        tasks_ai=TaskSuggester(
            uow_factory,
            access,
            model,
            consents,
            deps.rate_limiter,
            _quota_of(deps, "admit_tasks_suggest_per_week"),
            texts,
            deps.clock,
            student_search,
        ),
        assistant=AssistantService(
            access,
            UowAssistantData(uow_factory),
            student_search or NoStudentSearch(),
            assistant_model or UnavailableAssistantModel(),
            assistant_repo,
            consents,
            deps.rate_limiter,
            _quota_of(deps, "admit_assistant_per_day"),
            texts,
            deps.clock,
        ),
        calendar=calendar,
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
