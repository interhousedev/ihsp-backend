"""Builds the AI module: use cases, tools and the public `AiQueries`."""

from dataclasses import dataclass

from app.modules.ai.application.approve_tool_call import ApproveToolCall
from app.modules.ai.application.budget import BudgetService
from app.modules.ai.application.chat_views import ChatViews
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
from app.modules.ai.application.public_api import AiQueriesImpl
from app.modules.ai.application.purge_admin_chats import PurgeAdminChats
from app.modules.ai.application.regenerate_answer import RegenerateAnswer
from app.modules.ai.application.reject_tool_call import RejectToolCall
from app.modules.ai.application.rename_chat import RenameChat
from app.modules.ai.application.send_message import SendMessage
from app.modules.ai.application.set_message_feedback import SetMessageFeedback
from app.modules.ai.application.system_prompts import SystemPrompts
from app.modules.ai.application.tool_runner import ToolRunner
from app.modules.ai.application.tools.add_flashcards import AddFlashcards
from app.modules.ai.application.tools.add_notebook_sources import AddNotebookSources
from app.modules.ai.application.tools.admin_forward import (
    AdminReadTool,
    AdminWriteTool,
)
from app.modules.ai.application.tools.base import Tool
from app.modules.ai.application.tools.create_artifact import CreateArtifact
from app.modules.ai.application.tools.create_flashcard_set import CreateFlashcardSet
from app.modules.ai.application.tools.create_notebook import CreateNotebook
from app.modules.ai.application.tools.get_attendance import GetAttendance
from app.modules.ai.application.tools.get_flashcard_set import GetFlashcardSet
from app.modules.ai.application.tools.get_homework import GetHomework
from app.modules.ai.application.tools.get_lesson_materials import GetLessonMaterials
from app.modules.ai.application.tools.get_marks import GetMarks
from app.modules.ai.application.tools.get_my_subjects import GetMySubjects
from app.modules.ai.application.tools.get_notebook import GetNotebook
from app.modules.ai.application.tools.get_schedule import GetSchedule
from app.modules.ai.application.tools.get_subject_lessons import GetSubjectLessons
from app.modules.ai.application.tools.list_files import ListFiles
from app.modules.ai.application.tools.list_flashcard_sets import ListFlashcardSets
from app.modules.ai.application.tools.list_notebook_artifacts import (
    ListNotebookArtifacts,
)
from app.modules.ai.application.tools.list_notebooks import ListNotebooks
from app.modules.ai.application.tools.lms_catalog import make_author_tools
from app.modules.ai.application.tools.make_document import MakeDocument
from app.modules.ai.application.tools.read_file import ReadFile
from app.modules.ai.application.tools.read_notebook_source import ReadNotebookSource
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.application.tools.search_files import SearchFiles
from app.modules.ai.application.tools.search_notebook import SearchNotebook
from app.modules.ai.application.turn_result import TurnResults
from app.modules.ai.application.web_search import WebSearchService
from app.modules.ai.domain.admin_tools import ADMIN_TOOLS
from app.modules.ai.domain.tool_call import ToolAccess
from app.modules.ai.infrastructure.author_gate import LateAuthorGate
from app.modules.ai.infrastructure.fake_search import FakeWebSearch
from app.modules.ai.infrastructure.notebook_platform_search import (
    CompositePlatformSearch,
    LateLibrarySearch,
    NotebookPlatformSearch,
)
from app.modules.ai.infrastructure.redis_budget_store import (
    COURSE_PREFIX,
    RedisBudgetStore,
)
from app.modules.ai.infrastructure.redis_search_quota import RedisSearchQuotaStore
from app.modules.ai.infrastructure.redis_summary_store import RedisSummaryStore
from app.modules.ai.infrastructure.redis_turn_lock import RedisTurnLock
from app.modules.ai.infrastructure.uow import SqlAiUnitOfWork
from app.modules.ai.ports.budget_store import BudgetStore
from app.modules.ai.ports.search_quota import SearchQuotaStore
from app.modules.ai.ports.summary_store import SummaryStore
from app.modules.ai.ports.turn_lock import TurnLock
from app.modules.ai.ports.unit_of_work import UowFactory
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.ai import AdminToolBackend, AiQueries, LlmGateway
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.contracts.web_search import WebSearchApi, WebSearchGateway
from app.shared.wiring import ModuleDeps


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
    max_text_bytes: int,
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
        ReadFile(files, max_text_bytes),
        SearchFiles(files),
        ListNotebooks(bindings),
        GetNotebook(bindings),
        SearchNotebook(bindings),
        ReadNotebookSource(bindings),
        ListNotebookArtifacts(bindings),
        ListFlashcardSets(flashcards),
        GetFlashcardSet(flashcards),
        CreateFlashcardSet(flashcards),
        AddFlashcards(flashcards),
        CreateNotebook(files, bindings),
        AddNotebookSources(files, bindings),
        CreateArtifact(bindings),
        MakeDocument(files, bindings),
    ]


def make_admin_tools(
    backend: AdminToolBackend, identity: IdentityDirectory
) -> list[Tool]:
    """Return the Administration assistant's tools in their fixed order."""
    return [
        (
            AdminReadTool(d, backend)
            if d.access is ToolAccess.READ
            else AdminWriteTool(d, backend, identity)
        )
        for d in ADMIN_TOOLS
    ]


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
    overrides: AiOverrides | None = None,
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
    budget = BudgetService(
        over.budget_store or RedisBudgetStore(deps.redis),
        deps.clock,
        settings,
        course_store=over.course_budget_store
        or RedisBudgetStore(deps.redis, COURSE_PREFIX),
    )
    gate = LateAuthorGate(bindings, settings)
    guard = ChatGuard(gate, deps.rate_limiter, settings)
    locks = over.turn_lock or RedisTurnLock(deps.redis)
    registry = ToolRegistry(
        make_student_tools(
            schedule=schedule,
            classwork=classwork,
            marks=marks,
            files=files,
            flashcards=flashcards,
            bindings=bindings,
            max_text_bytes=settings.limits.ai_text_max_bytes,
        ),
        make_admin_tools(admin_tools, identity),
        make_author_tools(bindings, deps.i18n),
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
        prompts=SystemPrompts(gate, deps.clock),
        clock=deps.clock,
        settings=settings,
        i18n=deps.i18n,
    )
    decider = CallDecider(uow_factory=uow_factory, guard=guard, clock=deps.clock)
    searching = WebSearchService(
        store=over.search_quota_store or RedisSearchQuotaStore(deps.redis),
        gateway=web_search or FakeWebSearch(),
        llm=llm,
        clock=deps.clock,
        settings=settings,
        platform=CompositePlatformSearch(
            [NotebookPlatformSearch(bindings), LateLibrarySearch(bindings)]
        ),
    )
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
            locks=locks,
            locale=locale,
            results=results,
            web=searching,
            clock=deps.clock,
            settings=settings,
        ),
        regenerate_answer=RegenerateAnswer(
            uow_factory=uow_factory,
            guard=guard,
            continue_turn=continue_turn,
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
        purge_admin_chats=PurgeAdminChats(uow_factory=uow_factory, clock=deps.clock),
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
