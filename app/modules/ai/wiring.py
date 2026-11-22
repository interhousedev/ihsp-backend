"""Builds the AI module: use cases, tools and the public `AiQueries`."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.modules.ai.application.ai_analytics import AiAnalytics
from app.modules.ai.application.approve_tool_call import ApproveToolCall
from app.modules.ai.application.budget import BudgetService
from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.connectors import ConnectorAdmin, PipelineAdmin
from app.modules.ai.application.continue_turn import ContinueTurn
from app.modules.ai.application.create_chat import CreateChat
from app.modules.ai.application.decide_tool_call import CallDecider
from app.modules.ai.application.delete_chat import DeleteChat
from app.modules.ai.application.get_chat import GetChat
from app.modules.ai.application.get_usage import GetUsage
from app.modules.ai.application.history_summarizer import HistorySummarizer
from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.list_chats import ListChats
from app.modules.ai.application.locale import LocaleResolver
from app.modules.ai.application.owned_chat import ChatGuard
from app.modules.ai.application.project_service import ProjectService
from app.modules.ai.application.prompt_registry import (
    PromptAdmin,
    PromptAnalytics,
    PromptRegistry,
)
from app.modules.ai.application.public_api import AiQueriesImpl
from app.modules.ai.application.publish_requests import RequestPublisher
from app.modules.ai.application.purge_admin_chats import PurgeAdminChats
from app.modules.ai.application.purge_usage_events import PurgeUsageEvents
from app.modules.ai.application.purge_web_pages import PurgeWebPages
from app.modules.ai.application.regenerate_answer import RegenerateAnswer
from app.modules.ai.application.reject_tool_call import RejectToolCall
from app.modules.ai.application.rename_chat import RenameChat
from app.modules.ai.application.request_admin import RequestAdmin
from app.modules.ai.application.requests import AiRequests
from app.modules.ai.application.routing import RouteService
from app.modules.ai.application.send_message import SendMessage
from app.modules.ai.application.set_message_feedback import SetMessageFeedback
from app.modules.ai.application.system_prompts import (
    SystemPrompts,
    project_instructions_from,
)
from app.modules.ai.application.telegram_topics import TelegramTopics
from app.modules.ai.application.tool_runner import ToolRunner
from app.modules.ai.application.tools.add_flashcards import AddFlashcards
from app.modules.ai.application.tools.add_notebook_sources import AddNotebookSources
from app.modules.ai.application.tools.admin_forward import (
    AdminReadTool,
    AdminWriteTool,
)
from app.modules.ai.application.tools.admission import make_admission_tools
from app.modules.ai.application.tools.base import Tool
from app.modules.ai.application.tools.create_artifact import CreateArtifact
from app.modules.ai.application.tools.create_flashcard_set import CreateFlashcardSet
from app.modules.ai.application.tools.create_notebook import CreateNotebook
from app.modules.ai.application.tools.create_office_file import make_office_tools
from app.modules.ai.application.tools.find_feature import FindFeature
from app.modules.ai.application.tools.get_attendance import GetAttendance
from app.modules.ai.application.tools.get_flashcard_set import GetFlashcardSet
from app.modules.ai.application.tools.get_homework import GetHomework
from app.modules.ai.application.tools.get_lesson_materials import GetLessonMaterials
from app.modules.ai.application.tools.get_marks import GetMarks
from app.modules.ai.application.tools.get_my_subjects import GetMySubjects
from app.modules.ai.application.tools.get_notebook import GetNotebook
from app.modules.ai.application.tools.get_schedule import GetSchedule
from app.modules.ai.application.tools.get_subject_lessons import GetSubjectLessons
from app.modules.ai.application.tools.library_search import SearchLibrary
from app.modules.ai.application.tools.list_files import ListFiles
from app.modules.ai.application.tools.list_flashcard_sets import ListFlashcardSets
from app.modules.ai.application.tools.list_notebook_artifacts import (
    ListNotebookArtifacts,
)
from app.modules.ai.application.tools.list_notebooks import ListNotebooks
from app.modules.ai.application.tools.lms_catalog import make_author_tools
from app.modules.ai.application.tools.make_document import MakeDocument
from app.modules.ai.application.tools.read_chat_history import ReadChatHistory
from app.modules.ai.application.tools.read_file import ReadFile
from app.modules.ai.application.tools.read_notebook_source import ReadNotebookSource
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.application.tools.research_institution import (
    ResearchInstitution,
)
from app.modules.ai.application.tools.search_files import SearchFiles
from app.modules.ai.application.tools.search_knowledge_base import (
    SearchKnowledgeBase,
)
from app.modules.ai.application.tools.search_notebook import SearchNotebook
from app.modules.ai.application.tools.search_project_files import (
    SearchProjectFiles,
)
from app.modules.ai.application.tools.search_web import SearchWeb
from app.modules.ai.application.tools.show_ui_block import ShowUiBlock
from app.modules.ai.application.tracing_admin import TracingAdmin
from app.modules.ai.application.transcribe_audio import AudioSniffer, TranscribeAudio
from app.modules.ai.application.turn_result import TurnResults
from app.modules.ai.application.usage_report import UsageReport
from app.modules.ai.application.web_pages import WebPageIndex
from app.modules.ai.application.web_search import WebSearchService
from app.modules.ai.domain import prompts as chat_prompts
from app.modules.ai.domain.admin_tools import ADMIN_TOOLS
from app.modules.ai.domain.prompt_registry import PromptSlot
from app.modules.ai.domain.requests import AiRequestSpec, build_catalog
from app.modules.ai.domain.tool_call import ToolAccess
from app.modules.ai.infrastructure.analytics_reader import SqlAiAnalyticsReader
from app.modules.ai.infrastructure.author_gate import LateAuthorGate
from app.modules.ai.infrastructure.connector_clients import EnvConnectorRuntime
from app.modules.ai.infrastructure.connector_store import (
    SqlConnectorUnitOfWork,
    SqlRoutingLoader,
)
from app.modules.ai.infrastructure.connector_vault import (
    DisabledConnectorSecrets,
    VaultConnectorSecrets,
)
from app.modules.ai.infrastructure.exa_search import ExaWebSearch
from app.modules.ai.infrastructure.fake_exa import FakeExaClient
from app.modules.ai.infrastructure.notebook_platform_search import (
    CompositePlatformSearch,
    LateLibrarySearch,
    LateSharedSearch,
    NotebookPlatformSearch,
)
from app.modules.ai.infrastructure.prompt_store import (
    SqlPromptAnalyticsReader,
    SqlPromptUnitOfWork,
    SqlPromptVersionLoader,
)
from app.modules.ai.infrastructure.redis_budget_store import (
    COURSE_PREFIX,
    RedisBudgetStore,
)
from app.modules.ai.infrastructure.redis_search_quota import RedisSearchQuotaStore
from app.modules.ai.infrastructure.redis_summary_store import RedisSummaryStore
from app.modules.ai.infrastructure.redis_turn_lock import RedisTurnLock
from app.modules.ai.infrastructure.request_store import SqlRequestPublishUnitOfWork
from app.modules.ai.infrastructure.tracing_runtime import TracingRuntime
from app.modules.ai.infrastructure.uow import SqlAiUnitOfWork
from app.modules.ai.infrastructure.usage_reader import SqlUsageReader
from app.modules.ai.infrastructure.usage_store import SqlUsageStore
from app.modules.ai.ports.budget_store import BudgetStore
from app.modules.ai.ports.connectors import ConnectorSecrets, RoutingSnapshot
from app.modules.ai.ports.search_quota import SearchQuotaStore
from app.modules.ai.ports.summary_store import SummaryStore
from app.modules.ai.ports.turn_lock import TurnLock
from app.modules.ai.ports.unit_of_work import UowFactory
from app.modules.ai.ports.usage import FreeUsage
from app.settings import UrlsSettings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.ai import AdminToolBackend, AiQueries, LlmGateway
from app.shared.contracts.embeddings import EmbeddingIndex
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.contracts.web_search import WebSearchApi, WebSearchGateway
from app.shared.limits import LimitsProvider
from app.shared.wiring import ModuleDeps


def _chat_request(task: AiTask, summary: str) -> AiRequestSpec:
    return AiRequestSpec(
        id=f"ai.{task.value}.turn",
        owner_app="ai",
        task=task.value,
        template=PromptSlot(
            task.value, "priorities", "Priorities", chat_prompts.PRIORITIES
        ),
        args_schema={
            "type": "object",
            "properties": {
                "surface": {"type": "string"},
                "answer_now": {"type": "boolean"},
            },
            "required": ["surface", "answer_now"],
            "additionalProperties": False,
        },
        summary=summary,
    )


# AI requests this module declares; the AI module publishes them at startup.
AI_REQUESTS: tuple[AiRequestSpec, ...] = (
    _chat_request(AiTask.STUDENT_CHAT, "Student assistant: one model request"),
    _chat_request(
        AiTask.STUDENT_CHAT_SMART, "Student assistant, smart tier: one model request"
    ),
    _chat_request(AiTask.ADMIN_CHAT, "Administration assistant: one model request"),
)


@dataclass(slots=True)
class AiServices:
    """Use cases of the AI module (attribute name = use case file name)."""

    create_chat: CreateChat
    list_chats: ListChats
    get_chat: GetChat
    rename_chat: RenameChat
    delete_chat: DeleteChat
    send_message: SendMessage
    regenerate_answer: RegenerateAnswer
    set_message_feedback: SetMessageFeedback
    approve_tool_call: ApproveToolCall
    reject_tool_call: RejectToolCall
    get_usage: GetUsage
    purge_admin_chats: PurgeAdminChats
    public: AiQueries
    bindings: LateBindings
    web_search: WebSearchApi
    usage_report: UsageReport
    purge_usage_events: PurgeUsageEvents
    purge_web_pages: PurgeWebPages
    transcribe_audio: TranscribeAudio
    projects: ProjectService
    telegram_topics: TelegramTopics
    analytics: AiAnalytics
    # Editable prompts; set by the composition root (it builds them before the LLM).
    prompts: "PromptServices | None" = None
    # Connectors and pipeline routes; set by the composition root with the prompts.
    connectors: "ConnectorServices | None" = None


@dataclass(frozen=True, slots=True)
class PromptServices:
    """The editable prompts: the registry, its administration and its figures."""

    registry: PromptRegistry
    admin: PromptAdmin
    analytics: PromptAnalytics
    requests: AiRequests
    request_admin: RequestAdmin
    publisher: RequestPublisher
    catalog: tuple[AiRequestSpec, ...]


@dataclass(frozen=True, slots=True)
class ConnectorServices:
    """Connectors and pipeline routes: the router the gateways ask, and its admin."""

    routing: RouteService
    connectors: ConnectorAdmin
    pipelines: PipelineAdmin
    tracing: TracingAdmin


def build_connectors(
    deps: ModuleDeps,
    *,
    llm: LlmGateway,
    search: WebSearchGateway | None,
    tracing: TracingRuntime,
) -> ConnectorServices:
    """The route resolver over the stored routes, and the administration of both.

    Every fresh routing read also sets the Langfuse project and the per-pipeline
    tracing switches of `tracing`.
    """
    settings = deps.settings
    vault = settings.ai_connector_vault
    secrets: ConnectorSecrets = (
        VaultConnectorSecrets(vault) if vault.enabled else DisabledConnectorSecrets()
    )
    runtime = EnvConnectorRuntime(
        settings, secrets, llm=llm, search=search, redis=deps.redis
    )

    async def apply_tracing(snapshot: RoutingSnapshot) -> None:
        await tracing.apply(snapshot, secrets)

    routing = RouteService(
        settings,
        SqlRoutingLoader(deps.sessionmaker),
        runtime,
        on_load=apply_tracing,
    )

    def make_uow() -> SqlConnectorUnitOfWork:
        return SqlConnectorUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return ConnectorServices(
        routing=routing,
        connectors=ConnectorAdmin(
            make_uow,
            secrets,
            runtime,
            routing,
            allow_plain_local_urls=settings.env != "prod",
        ),
        pipelines=PipelineAdmin(
            make_uow,
            runtime,
            routing,
            deps.clock,
        ),
        tracing=TracingAdmin(
            make_uow,
            secrets,
            routing,
            deps.clock,
            allow_plain_local_urls=settings.env != "prod",
        ),
    )


def build_prompts(
    deps: ModuleDeps,
    slots: Sequence[PromptSlot],
    declared: Sequence[AiRequestSpec] = (),
) -> PromptServices:
    """The registry over the stored versions, its admin and analytics, and requests.

    `declared` are the requests the modules declare; each prompt slot none of them
    renders gets an automatic one. A duplicate request id raises here (startup).
    """
    registry = PromptRegistry(slots, SqlPromptVersionLoader(deps.sessionmaker))
    catalog = tuple(build_catalog(slots, declared))

    def make_uow() -> SqlPromptUnitOfWork:
        return SqlPromptUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    def make_publish_uow() -> SqlRequestPublishUnitOfWork:
        return SqlRequestPublishUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return PromptServices(
        registry=registry,
        admin=PromptAdmin(registry, make_uow, deps.clock),
        analytics=PromptAnalytics(SqlPromptAnalyticsReader(deps.sessionmaker)),
        requests=AiRequests(catalog, registry),
        request_admin=RequestAdmin(make_publish_uow),
        publisher=RequestPublisher(make_publish_uow, deps.clock),
        catalog=catalog,
    )


async def publish_prompts_on_startup(prompts: PromptServices, enabled: bool) -> None:
    """Publish the code's prompt defaults and the request registry (api process)."""
    if not enabled:
        return
    await prompts.publisher.publish(prompts.registry.slots(), prompts.catalog)


@dataclass(frozen=True, slots=True)
class AiOverrides:
    """Replacements for the Redis stores, the lock and the UoW (tests pass fakes)."""

    budget_store: BudgetStore | None = None
    course_budget_store: BudgetStore | None = None  # the course staff pool
    summary_store: SummaryStore | None = None
    search_quota_store: SearchQuotaStore | None = None
    turn_lock: TurnLock | None = None
    uow_factory: UowFactory | None = None


def make_student_tools(
    *,
    schedule: ScheduleQueries,
    classwork: ClassworkQueries,
    marks: MarksQueries,
    files: FilesApi,
    flashcards: FlashcardsApi,
    bindings: LateBindings,
    limits: LimitsProvider,
    uow_factory: UowFactory,
    urls: UrlsSettings,
) -> list[Tool]:
    """Return the student assistant's tools in their fixed order."""
    return [
        GetMySubjects(marks),
        GetSubjectLessons(classwork, marks),
        GetLessonMaterials(schedule, bindings),
        GetSchedule(schedule),
        GetHomework(classwork),
        GetMarks(marks),
        GetAttendance(classwork),
        ListFiles(files),
        ReadFile(files, limits),
        SearchFiles(files),
        ListNotebooks(bindings),
        GetNotebook(bindings),
        SearchNotebook(bindings),
        ReadNotebookSource(bindings),
        ListNotebookArtifacts(bindings),
        SearchWeb(bindings, limits),
        ResearchInstitution(bindings),
        SearchLibrary(bindings),
        SearchKnowledgeBase(bindings, "student"),
        FindFeature(urls),
        SearchProjectFiles(uow_factory, files),
        ListFlashcardSets(flashcards),
        GetFlashcardSet(flashcards),
        CreateFlashcardSet(flashcards),
        AddFlashcards(flashcards),
        CreateNotebook(files, bindings),
        AddNotebookSources(files, bindings),
        CreateArtifact(bindings),
        MakeDocument(files, bindings),
        *make_office_tools(files, bindings),
    ]


def make_admin_tools(
    backend: AdminToolBackend,
    identity: IdentityDirectory,
    bindings: LateBindings,
    urls: UrlsSettings,
) -> list[Tool]:
    """Return the Administration assistant's tools in their fixed order."""
    tools: list[Tool] = [
        (
            AdminReadTool(d, backend)
            if d.access is ToolAccess.READ
            else AdminWriteTool(d, backend, identity)
        )
        for d in ADMIN_TOOLS
    ]
    tools.append(SearchKnowledgeBase(bindings, "admin"))
    tools.append(FindFeature(urls))
    return tools


def build(
    deps: ModuleDeps,
    *,
    llm: LlmGateway,
    identity: IdentityDirectory,
    schedule: ScheduleQueries,
    classwork: ClassworkQueries,
    marks: MarksQueries,
    files: FilesApi,
    flashcards: FlashcardsApi,
    admin_tools: AdminToolBackend,
    links: LinksApi | None = None,
    web_search: WebSearchGateway | None = None,
    embeddings: Callable[[], EmbeddingIndex | None] | None = None,
    overrides: AiOverrides | None = None,
    sniffer: AudioSniffer,
    free_usage: FreeUsage | None = None,
    requests: AiRequests | None = None,
) -> AiServices:
    """Wire the module.

    `links` and the share lookup are optional because the links module itself
    needs `AiServices.public`; bind them later with `services.bindings`. Without a
    `web_search` gateway the fake one answers (development and most tests).
    """
    over = overrides or AiOverrides()
    settings = deps.settings
    bindings = LateBindings(links=links)
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    limits = deps.effective_limits
    budget = BudgetService(
        over.budget_store or RedisBudgetStore(deps.redis),
        deps.clock,
        settings,
        course_store=over.course_budget_store
        or RedisBudgetStore(deps.redis, COURSE_PREFIX),
        limits=limits,
    )
    gate = LateAuthorGate(bindings, settings)
    guard = ChatGuard(
        gate, deps.rate_limiter, settings, limits=limits, bindings=bindings
    )
    locks = over.turn_lock or RedisTurnLock(deps.redis)
    history = ReadChatHistory(uow_factory)  # every assistant (AI-EFF-3)
    registry = ToolRegistry(
        [
            *make_student_tools(
                schedule=schedule,
                classwork=classwork,
                marks=marks,
                files=files,
                flashcards=flashcards,
                bindings=bindings,
                limits=deps.effective_limits,
                uow_factory=uow_factory,
                urls=settings.urls,
            ),
            history,
        ],
        [*make_admin_tools(admin_tools, identity, bindings, settings.urls), history],
        [
            *make_author_tools(bindings, deps.i18n),
            *make_office_tools(files, bindings),
            history,
        ],
        telegram=[ShowUiBlock()] if settings.ai.openui_enabled else [],
        admission=[*make_admission_tools(bindings), history],
        staff=[
            *make_author_tools(bindings, deps.i18n),
            *make_office_tools(files, bindings),
            history,
        ],
    )
    locale = LocaleResolver(identity)
    views = ChatViews(deps.i18n)
    results = TurnResults(views, budget, deps.clock)
    summarizer = HistorySummarizer(
        uow_factory,
        over.summary_store or RedisSummaryStore(deps.redis),
        llm,
        budget,
        settings,
    )
    runner = ToolRunner(registry, deps.clock)
    continue_turn = ContinueTurn(
        uow_factory=uow_factory,
        llm=llm,
        registry=registry,
        runner=runner,
        budget=budget,
        summarizer=summarizer,
        prompts=SystemPrompts(
            gate,
            deps.clock,
            limits,
            openui=settings.ai.openui_enabled,
            admission_openui=settings.ai.openui_admission_enabled,
            projects=project_instructions_from(uow_factory),
            uni_chat=lambda: bindings.uni_chat,
        ),
        clock=deps.clock,
        settings=settings,
        i18n=deps.i18n,
        limits=limits,
        requests=requests,
    )
    decider = CallDecider(uow_factory=uow_factory, guard=guard, clock=deps.clock)
    pages = WebPageIndex(
        uow_factory=uow_factory,
        embeddings=embeddings or (lambda: None),
        clock=deps.clock,
        settings=settings,
    )
    searching = WebSearchService(
        store=over.search_quota_store or RedisSearchQuotaStore(deps.redis),
        gateway=web_search
        or ExaWebSearch(FakeExaClient(), settings.web_search, settings.exa),
        llm=llm,
        clock=deps.clock,
        settings=settings,
        limits=limits,
        pages=pages,
        usage=free_usage,
        platform=CompositePlatformSearch(
            [
                NotebookPlatformSearch(bindings),
                LateLibrarySearch(bindings),
                LateSharedSearch(bindings),
            ]
        ),
    )
    bindings.web = searching
    return AiServices(
        create_chat=CreateChat(
            uow_factory=uow_factory,
            guard=guard,
            clock=deps.clock,
            settings=settings,
            i18n=deps.i18n,
            locale=locale,
            views=views,
        ),
        list_chats=ListChats(
            uow_factory=uow_factory, guard=guard, clock=deps.clock, views=views
        ),
        get_chat=GetChat(
            uow_factory=uow_factory,
            guard=guard,
            clock=deps.clock,
            locale=locale,
            views=views,
            bindings=bindings,
        ),
        rename_chat=RenameChat(uow_factory=uow_factory, guard=guard, views=views),
        delete_chat=DeleteChat(uow_factory=uow_factory, guard=guard, clock=deps.clock),
        send_message=SendMessage(
            uow_factory=uow_factory,
            guard=guard,
            files=files,
            continue_turn=continue_turn,
            budget=budget,
            locks=locks,
            locale=locale,
            results=results,
            web=searching,
            clock=deps.clock,
            settings=settings,
            i18n=deps.i18n,
            bindings=bindings,
        ),
        regenerate_answer=RegenerateAnswer(
            uow_factory=uow_factory,
            guard=guard,
            continue_turn=continue_turn,
            budget=budget,
            locks=locks,
            locale=locale,
            results=results,
            clock=deps.clock,
            settings=settings,
        ),
        set_message_feedback=SetMessageFeedback(uow_factory=uow_factory, guard=guard),
        approve_tool_call=ApproveToolCall(
            uow_factory=uow_factory,
            decider=decider,
            runner=runner,
            continue_turn=continue_turn,
            locks=locks,
            locale=locale,
            results=results,
        ),
        reject_tool_call=RejectToolCall(
            uow_factory=uow_factory,
            decider=decider,
            continue_turn=continue_turn,
            locks=locks,
            locale=locale,
            results=results,
        ),
        get_usage=GetUsage(budget=budget, guard=guard),
        usage_report=UsageReport(
            reader=SqlUsageReader(deps.sessionmaker),
            identity=identity,
            clock=deps.clock,
        ),
        purge_usage_events=PurgeUsageEvents(
            store=SqlUsageStore(deps.sessionmaker),
            clock=deps.clock,
            retention_days=settings.ai.usage_retention_days,
        ),
        purge_admin_chats=PurgeAdminChats(uow_factory=uow_factory, clock=deps.clock),
        purge_web_pages=PurgeWebPages(pages),
        projects=ProjectService(uow_factory=uow_factory, files=files, clock=deps.clock),
        telegram_topics=TelegramTopics(uow_factory),
        analytics=AiAnalytics(
            reader=SqlAiAnalyticsReader(deps.sessionmaker),
            identity=identity,
            clock=deps.clock,
        ),
        transcribe_audio=TranscribeAudio(
            llm=llm,
            budget=budget,
            rate_limiter=deps.rate_limiter,
            settings=settings,
            locale=locale,
            sniffer=sniffer,
        ),
        public=AiQueriesImpl(
            uow_factory=uow_factory, clock=deps.clock, locale=locale, views=views
        ),
        bindings=bindings,
        web_search=searching,
    )


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlAiUnitOfWork:
        return SqlAiUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
