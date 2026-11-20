"""Builds the admission module (container.admission)."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import ResolveAdmissionActor
from app.modules.admission.application.app_review import AppReviewService
from app.modules.admission.application.app_review_inputs import UowReviewInputs
from app.modules.admission.application.assistant import AssistantService
from app.modules.admission.application.budget import BudgetService
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
from app.modules.admission.application.consultations import ConsultationService
from app.modules.admission.application.courses import CourseService
from app.modules.admission.application.deadlines import DeadlineService
from app.modules.admission.application.document_process import DocumentProcessService
from app.modules.admission.application.documents import DocumentService
from app.modules.admission.application.essay_invites import EssayInviteService
from app.modules.admission.application.essay_reviews import EssayReviewService
from app.modules.admission.application.essays import (
    EssayCoach,
    EssayService,
    UowEssayReader,
)
from app.modules.admission.application.exemplar_search import UowExemplarSource
from app.modules.admission.application.exemplars import ExemplarService
from app.modules.admission.application.goal_plan import GoalPlanService
from app.modules.admission.application.goal_plan_suggest import GoalPlanSuggester
from app.modules.admission.application.interview import ItemInterviewService
from app.modules.admission.application.item_grade import ItemGradeService
from app.modules.admission.application.items import ItemService
from app.modules.admission.application.kb import KbService
from app.modules.admission.application.list_plan import ListPlanService
from app.modules.admission.application.matching import MatchService
from app.modules.admission.application.memory_notes import MemoryNoteService
from app.modules.admission.application.mentoring import MentoringService
from app.modules.admission.application.nudges import NudgeService
from app.modules.admission.application.opportunities import (
    LmsCourseLookup,
    OpportunityService,
)
from app.modules.admission.application.opportunity_comments import OppCommentService
from app.modules.admission.application.opportunity_intake import OpportunityIntake
from app.modules.admission.application.opportunity_planner import OpportunityPlanner
from app.modules.admission.application.orgs import OrgService
from app.modules.admission.application.outcomes import OutcomeService
from app.modules.admission.application.privacy import Eraser, PrivacyService
from app.modules.admission.application.profile import ProfileService
from app.modules.admission.application.profile_alignment import AlignmentService
from app.modules.admission.application.profile_details import ProfileDetailsService
from app.modules.admission.application.prompt_studio import (
    CoreStudioRunner,
    PromptStudioService,
)
from app.modules.admission.application.proofs import ProofService
from app.modules.admission.application.readiness import ReadinessService
from app.modules.admission.application.review import ItemReviewService
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.application.staff import StaffService
from app.modules.admission.application.supp_prompts import SuppPromptService
from app.modules.admission.application.tasks import TaskService
from app.modules.admission.application.tasks_suggest import TaskSuggester
from app.modules.admission.application.test_scores import ScoreService
from app.modules.admission.application.transcripts import TranscriptService
from app.modules.admission.application.uni_advice import UniAdviceService
from app.modules.admission.application.uni_chat import UniChatService
from app.modules.admission.application.voice import VoiceService
from app.modules.admission.application.words import WordsService
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.app_review_repository import (
    SqlAppReviewRepository,
)
from app.modules.admission.infrastructure.assistant_adapters import UowAssistantData
from app.modules.admission.infrastructure.calendar_repository import (
    SqlCalendarStore,
)
from app.modules.admission.infrastructure.catalog_data import study_fields as _fields
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)
from app.modules.admission.infrastructure.kb_repository import SqlKbRepository
from app.modules.admission.infrastructure.uni_chat_repository import (
    SqlUniChatRepository,
)
from app.modules.admission.infrastructure.uow import SqlAdmissionUnitOfWork
from app.modules.admission.ports.ai import PromptSource, QuotaOf, StructuredAi
from app.modules.admission.ports.calendar import CalendarStore
from app.modules.admission.ports.consent import (
    MemoryPurposeConsents,
    PurposeConsentStore,
)
from app.modules.admission.ports.courses import CourseSources
from app.modules.admission.ports.essay_crypto import EssayCipher
from app.modules.admission.ports.essays import EssayReader
from app.modules.admission.ports.prompt_studio import PromptStudioAdmin
from app.modules.admission.ports.staff import StaffDirectory
from app.modules.admission.ports.student_search import StudentDataSearch
from app.modules.admission.ports.uni_chat import UniChats, UniPageReader
from app.modules.admission.ports.unit_of_work import UowFactory
from app.modules.admission.ports.voice import VoiceAi
from app.modules.ai.domain.requests import AiRequestSpec
from app.modules.notebooks.application.llm import NotebookLlm
from app.shared.contracts.academic import AcademicMembership
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.web_search import WebSearchApi, WebSearchGateway
from app.shared.wiring import ModuleDeps

# AI requests this module declares; the AI module publishes them at startup.
AI_REQUESTS: tuple[AiRequestSpec, ...] = ()


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
    mentoring: MentoringService
    catalog: CatalogService
    catalog_proposals: CatalogProposalService
    supp_prompts: SuppPromptService
    chooser: ListService
    budget: BudgetService
    chances: ChancesService
    catalog_research: CatalogResearch | None
    uow_factory: UowFactory
    profile: ProfileService
    words: WordsService
    alignment: AlignmentService
    proofs: ProofService
    documents: DocumentService
    transcripts: TranscriptService
    deadlines: DeadlineService
    outcomes: OutcomeService
    nudges: NudgeService
    items: ItemService
    goal_plan: GoalPlanService
    goal_plan_suggest: GoalPlanSuggester
    essays: EssayService
    essay_coach: EssayCoach
    essay_reader: EssayReader
    item_reviews: ItemReviewService
    item_grades: ItemGradeService
    item_interviews: ItemInterviewService
    opportunity_intake: OpportunityIntake
    opportunities: OpportunityService
    orgs: OrgService
    opportunity_comments: OppCommentService
    opportunity_planner: OpportunityPlanner
    app_review: AppReviewService
    career: CareerService
    career_ai: CareerSuggester
    voice: VoiceService | None
    list_plan: ListPlanService
    calendar: CalendarService
    tasks: TaskService
    test_scores: ScoreService
    consultations: ConsultationService
    profile_details: ProfileDetailsService
    document_process: DocumentProcessService
    matching: MatchService
    readiness: ReadinessService
    tasks_ai: TaskSuggester
    assistant: AssistantService
    memory_notes: MemoryNoteService
    application_data: UowAssistantData  # read-only view for /mcp/admission
    uni_chat: UniChatService
    uni_advice: UniAdviceService
    kb: KbService
    cipher: EssayCipher
    essay_reviews: EssayReviewService
    essay_invites: EssayInviteService
    exemplars: ExemplarService
    prompt_studio: PromptStudioService


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
    erasers: Sequence[Eraser] = (),
    final_erasers: Sequence[Eraser] = (),
    uni_chats: UniChats | None = None,
    uni_web: WebSearchApi | None = None,
    uni_pages: UniPageReader | None = None,
    cipher: EssayCipher | None = None,
    studio_admin: PromptStudioAdmin,
) -> AdmissionServices:
    """Wire the module; without `purpose_consents` they live in process memory."""
    over = overrides or AdmissionOverrides()
    cipher = cipher or AesGcmEssayCipher(MemoryEssayKeyStore())
    uow_factory = over.uow_factory or _sql_uow_factory(deps, cipher)
    settings = deps.settings.admission
    grades = settings.eligible_grades
    consents = purpose_consents or MemoryPurposeConsents()
    access = AccessPolicy(
        uow_factory,
        membership,
        consents,
        deps.clock,
        grades,
        identity,
    )
    runtime = RuntimeSettingsService(uow_factory, ttl=settings.runtime_cache_seconds)
    model = ai or UnavailableAi()
    texts = prompts or BuiltinPrompts()
    kb = KbService(SqlKbRepository(deps.sessionmaker), deps.clock)
    limits = deps.effective_limits

    async def org_exists(org_id: UUID) -> bool:
        async with uow_factory() as uow:
            return await uow.orgs.get(org_id) is not None

    opportunities = OpportunityService(
        uow_factory, access, deps.clock, lms_courses, deps.rate_limiter, org_exists
    )
    chooser = ListService(uow_factory, access, runtime, settings, deps.clock, identity)
    budget = BudgetService(chooser)
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
    uni = UniChatService(
        uow_factory,
        access,
        consents,
        SqlUniChatRepository(deps.sessionmaker),
        uni_chats,
        UowAssistantData(uow_factory),
        uni_web,
        deps.clock,
        uni_pages,
    )
    uni_advice = UniAdviceService(
        uow_factory,
        access,
        consents,
        SqlUniChatRepository(deps.sessionmaker),
        UowAssistantData(uow_factory),
        model,
        deps.rate_limiter,
        _quota_of(deps, "admit_list_suggest_per_week"),
        texts,
        deps.clock,
    )
    exemplar_source = UowExemplarSource(uow_factory, deps.clock)
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
            erasers=[*erasers, uni.erase],
            file_remover=files.delete_file if files else None,
            final_erasers=[*final_erasers, cipher.forget],
        ),
        catalog=CatalogService(uow_factory),
        catalog_proposals=CatalogProposalService(
            uow_factory,
            deps.clock,
            deps.rate_limiter,
            settings.catalog_proposals_per_day,
        ),
        supp_prompts=SuppPromptService(
            uow_factory, CatalogProposalService(uow_factory, deps.clock).can_review
        ),
        chooser=chooser,
        budget=budget,
        chances=ChancesService(uow_factory, runtime, settings),
        catalog_research=CatalogResearch(uow_factory, llm, texts) if llm else None,
        uow_factory=uow_factory,
        cipher=cipher,
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
        documents=DocumentService(
            uow_factory, access, deps.clock, files, identity, limits
        ),
        transcripts=TranscriptService(
            uow_factory, access, runtime, deps.clock, membership, files, identity
        ),
        deadlines=DeadlineService(uow_factory, access, deps.clock),
        outcomes=OutcomeService(uow_factory, access, identity),
        nudges=NudgeService(uow_factory, deps.clock),
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
            cipher=cipher,
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
        item_grades=ItemGradeService(
            uow_factory,
            access,
            model,
            consents,
            texts,
            deps.rate_limiter,
            _quota_of(deps, "admit_item_review_per_day"),
        ),
        item_interviews=ItemInterviewService(
            uow_factory, access, model, consents, texts
        ),
        opportunity_intake=OpportunityIntake(
            model, texts, web_search=web_search, profile_of=profile_of
        ),
        opportunities=opportunities,
        orgs=OrgService(uow_factory, opportunities, deps.clock),
        opportunity_comments=OppCommentService(
            uow_factory, opportunities, deps.clock, identity
        ),
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
        consultations=ConsultationService(uow_factory, access, deps.clock, identity),
        profile_details=ProfileDetailsService(uow_factory, access, deps.clock),
        document_process=DocumentProcessService(uow_factory, access),
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
            consents,
            deps.rate_limiter,
            _quota_of(deps, "admit_assistant_per_day"),
            kb,
            opportunities,
            chooser,
            CatalogService(uow_factory),
            CourseService(uow_factory, access, course_sources),
            course_sources,
            ResolveAdmissionActor(uow_factory, membership, deps.clock, grades),
        ),
        kb=kb,
        memory_notes=MemoryNoteService(uow_factory, access, deps.clock),
        application_data=UowAssistantData(uow_factory),
        calendar=calendar,
        uni_chat=uni,
        uni_advice=uni_advice,
        essay_reviews=EssayReviewService(
            uow_factory,
            access,
            model,
            consents,
            deps.clock,
            deps.rate_limiter,
            _quota_of(deps, "admit_essay_review_per_week"),
            _quota_of(deps, "admit_essay_uni_review_per_week"),
            texts,
            exemplar_source,
            cipher,
        ),
        essay_invites=EssayInviteService(
            uow_factory, access, deps.clock, deps.rate_limiter
        ),
        exemplars=ExemplarService(uow_factory, deps.clock, deps.rate_limiter),
        prompt_studio=PromptStudioService(
            studio_admin,
            CoreStudioRunner(model),
            texts,
            uow_factory,
            deps.clock,
            deps.rate_limiter,
            per_day=_studio_runs_of(deps),
        ),
    )


def _studio_runs_of(deps: ModuleDeps) -> Callable[[], Awaitable[int | None]]:
    """Read the studio's daily run limit at call time (the same for all staff)."""

    async def read() -> int | None:
        value = (await deps.effective_limits.current()).admit_essay_studio_runs_per_day
        return None if value < 0 else int(value)

    return read


def _quota_of(deps: ModuleDeps, name: str) -> QuotaOf:
    """Read a soft limit at call time, so a change on the admin page applies."""

    async def read(user_id: UUID) -> int | None:
        value = getattr(await deps.effective_limits.for_user(user_id), name)
        return None if value is None else int(value)

    return read


def _sql_uow_factory(deps: ModuleDeps, cipher: EssayCipher) -> UowFactory:
    """Return a factory of SQL units of work on the shared sessionmaker."""

    def factory() -> SqlAdmissionUnitOfWork:
        return SqlAdmissionUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
            notification_outbox=deps.notification_outbox,
            cipher=cipher,
        )

    return factory
