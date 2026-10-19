"""Shared collaborators of the notebooks use cases (built once per process)."""

from dataclasses import dataclass, field

from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.context_builder import ContextBuilder
from app.modules.notebooks.application.course_context import CourseContextLoader
from app.modules.notebooks.application.get_usage import GetUsage
from app.modules.notebooks.application.history_compactor import HistoryCompactor
from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.application.multi_hop_retrieval import MultiHopRetrieval
from app.modules.notebooks.application.query_decomposer import QueryDecomposer
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.application.retrieval_expander import RetrievalExpander
from app.modules.notebooks.application.school_knowledge import SchoolKnowledge
from app.modules.notebooks.infrastructure.lms_course_gate import (
    NO_COURSES,
    LmsCourseGate,
)
from app.modules.notebooks.infrastructure.redis_budget_store import (
    COURSE_PREFIX as BUDGET_COURSE_PREFIX,
)
from app.modules.notebooks.infrastructure.redis_budget_store import RedisBudgetStore
from app.modules.notebooks.infrastructure.redis_compact_store import RedisCompactStore
from app.modules.notebooks.infrastructure.redis_quota_store import (
    COURSE_PREFIX as QUOTA_COURSE_PREFIX,
)
from app.modules.notebooks.infrastructure.redis_quota_store import RedisQuotaStore
from app.modules.notebooks.infrastructure.redis_turn_lock import RedisTurnLock
from app.modules.notebooks.infrastructure.uow import SqlNotebooksUnitOfWork
from app.modules.notebooks.ports.budget_store import BudgetStore
from app.modules.notebooks.ports.compact_store import CompactStore
from app.modules.notebooks.ports.course_gate import CourseGate
from app.modules.notebooks.ports.quota_store import QuotaStore
from app.modules.notebooks.ports.turn_lock import TurnLock
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.contracts.ai import LlmGateway
from app.shared.contracts.embeddings import EmbeddingIndex
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.lms import LmsWorkspace
from app.shared.contracts.school_knowledge import (
    KnowledgeGapReporter,
    KnowledgeLookup,
)
from app.shared.contracts.web_search import WebSearchApi
from app.shared.wiring import ModuleDeps


def _context(
    llm: NotebookLlm, settings: Settings, embeddings: EmbeddingIndex | None
) -> ContextBuilder:
    """The context builder with the small-model retrieval helpers (off by default)."""
    expander = RetrievalExpander(
        QueryDecomposer(llm, settings), MultiHopRetrieval(llm, settings)
    )
    return ContextBuilder(settings, embeddings, expander)


@dataclass(frozen=True, slots=True)
class NotebooksCore:
    """What every slice of the module needs."""

    deps: ModuleDeps
    uow_factory: UowFactory
    llm: NotebookLlm
    budget: NotebookBudget
    quota: QuotaService
    locale: LocaleResolver
    context: ContextBuilder
    usage: GetUsage
    turn_lock: TurnLock
    web_search: WebSearchApi | None = None  # None: web search is not available
    embeddings: EmbeddingIndex | None = None  # None: retrieval by words only
    # Course workspaces: the LMS side (None in a process without the LMS).
    workspace: LmsWorkspace | None = None
    course_context: CourseContextLoader = field(
        default_factory=lambda: CourseContextLoader(None)
    )
    # Summaries of older chat turns (None: the last messages only, no summary).
    compactor: HistoryCompactor | None = None
    # School facts for a chat without sources (None: no knowledge base wired).
    school_knowledge: SchoolKnowledge | None = None


@dataclass(frozen=True, slots=True)
class CoreOverrides:
    """Replacements for the SQL unit of work and the Redis stores (tests)."""

    uow_factory: UowFactory | None = None
    budget_store: BudgetStore | None = None
    quota_store: QuotaStore | None = None
    turn_lock: TurnLock | None = None
    compact_store: CompactStore | None = None


def sql_uow_factory(
    deps: ModuleDeps, course_gate: CourseGate = NO_COURSES
) -> UowFactory:
    """The SQL unit of work with the module's outbox/audit writers."""

    def make() -> SqlNotebooksUnitOfWork:
        return SqlNotebooksUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
            course_gate=course_gate,
        )

    return make


def _budget(deps: ModuleDeps, store: BudgetStore | None) -> NotebookBudget:
    """The student pool with the pool of course workspaces next to it."""
    settings = deps.settings
    limits = deps.effective_limits
    course = NotebookBudget(
        RedisBudgetStore(deps.redis, prefix=BUDGET_COURSE_PREFIX),
        deps.clock,
        settings,
        for_course=True,
        limits=limits,
    )
    return NotebookBudget(
        store or RedisBudgetStore(deps.redis),
        deps.clock,
        settings,
        course=course,
        limits=limits,
    )


def _quota(deps: ModuleDeps, store: QuotaStore | None) -> QuotaService:
    """The student output quotas with the course workspace quotas next to them."""
    settings = deps.settings
    limits = deps.effective_limits
    course = QuotaService(
        RedisQuotaStore(deps.redis, prefix=QUOTA_COURSE_PREFIX),
        deps.clock,
        settings,
        for_course=True,
        limits=limits,
    )
    return QuotaService(
        store or RedisQuotaStore(deps.redis),
        deps.clock,
        settings,
        course=course,
        limits=limits,
    )


def build_core(
    deps: ModuleDeps,
    *,
    gateway: LlmGateway,
    identity: IdentityDirectory,
    overrides: CoreOverrides | None = None,
    web_search: WebSearchApi | None = None,
    workspace: LmsWorkspace | None = None,
    embeddings: EmbeddingIndex | None = None,
    knowledge: KnowledgeLookup | None = None,
    knowledge_gaps: KnowledgeGapReporter | None = None,
) -> NotebooksCore:
    """Build the shared services; `overrides` replace the stores (tests).

    `workspace` (the LMS side of course workspaces) opens the workspaces to the
    course staff; without it no course workspace can be opened. `embeddings` turns
    retrieval into hybrid (words and meaning); None keeps it lexical.
    """
    over = overrides or CoreOverrides()
    settings = deps.settings
    budget = _budget(deps, over.budget_store)
    quota = _quota(deps, over.quota_store)
    gate: CourseGate = (
        NO_COURSES if workspace is None else LmsCourseGate(workspace, settings)
    )
    llm = NotebookLlm(gateway, settings)
    return NotebooksCore(
        deps=deps,
        uow_factory=over.uow_factory or sql_uow_factory(deps, gate),
        llm=llm,
        budget=budget,
        quota=quota,
        locale=LocaleResolver(identity),
        context=_context(llm, settings, embeddings),
        usage=GetUsage(budget, quota, settings, deps.effective_limits),
        turn_lock=over.turn_lock or RedisTurnLock(deps.redis),
        web_search=web_search,
        embeddings=embeddings,
        workspace=workspace,
        course_context=CourseContextLoader(workspace),
        school_knowledge=(
            SchoolKnowledge(llm, knowledge, knowledge_gaps)
            if knowledge is not None
            else None
        ),
        compactor=HistoryCompactor(
            llm, over.compact_store or RedisCompactStore(deps.redis), settings
        ),
    )
