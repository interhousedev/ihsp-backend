"""The composition root: builds the container for one process.

Wiring rules: each process (`PLANS`) builds only the modules it serves and holds only
the credentials it needs; modules talk to each other through the contracts in
`app/shared/contracts`, never by importing another module's internals.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from app.bootstrap.adapters.admin_tools import AdminToolBackendAdapter
from app.bootstrap.adapters.composition.library_platform_search import (
    LibraryPlatformSearch,
)
from app.bootstrap.adapters.composition.shared_platform_search import (
    SharedPlatformSearch,
)
from app.bootstrap.adapters.emis_source import make_emis_source
from app.bootstrap.adapters.lazy_proxy import LazyProxy
from app.bootstrap.adapters.library_academic import LibraryAcademicAdapter
from app.bootstrap.adapters.library_lessons import LibraryLessonsAdapter
from app.bootstrap.adapters.mail_suspension import MailSuspensionAdapter
from app.bootstrap.adapters.mcp_ports import ConnectorCoursesAdapter, McpAuditAdapter
from app.bootstrap.adapters.notebook_terms import NotebookTermsAdapter
from app.bootstrap.adapters.signature_sniffer import SignatureSniffer
from app.bootstrap.adapters.telegram import make_telegram_sender
from app.bootstrap.adapters.term_resolver import TermResolverAdapter
from app.bootstrap.adapters.usage_resolver import UsageResolverAdapter
from app.bootstrap.container import Container, build_infrastructure
from app.modules.academic.wiring import (
    AcademicModule,
    build_assessments,
    build_classwork,
    build_emis_import,
    build_marks,
    build_schedule,
    build_teaching,
)
from app.modules.admin.infrastructure.limit_snapshot import load_limit_snapshot
from app.modules.admin.wiring import build as build_admin
from app.modules.ai.infrastructure.gateway_factory import (
    make_embedding_gateway,
    make_llm_gateway,
    make_web_search_gateway,
)
from app.modules.ai.infrastructure.recording_gateways import (
    RecordingEmbeddings,
    RecordingLlmGateway,
    RecordingWebSearch,
    UsageRecorder,
)
from app.modules.ai.infrastructure.usage_store import SqlUsageStore
from app.modules.ai.wiring import build as build_ai
from app.modules.dashboard.wiring import build as build_dashboard
from app.modules.files.ports.content_sniffer import ContentSniffer
from app.modules.files.wiring import build as build_files
from app.modules.flashcards.ports.share_resolver import ShareResolver
from app.modules.flashcards.wiring import build as build_flashcards
from app.modules.identity.application.register_ports import CredentialStore
from app.modules.identity.infrastructure.audit_writer import write_audit_events
from app.modules.identity.infrastructure.hydra.factory import build_hydra_admin
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.wiring import build as build_identity
from app.modules.library.wiring import build as build_library
from app.modules.links.wiring import build as build_links
from app.modules.lms.wiring import build as build_lms
from app.modules.notebooks.application.export.render import DocumentExporter
from app.modules.notebooks.infrastructure.web_fetcher import HttpWebFetcher
from app.modules.notebooks.wiring import build as build_notebooks
from app.modules.notebooks.wiring_studio import LmsApplyPorts
from app.modules.notify.infrastructure.outbox_writer import write_notifications
from app.modules.notify.ports.push_sender import PushSender
from app.modules.notify.wiring import build as build_notify
from app.modules.vectors.wiring import build as build_vectors
from app.settings import Settings
from app.shared.actor import Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.ai import AiQueries, LlmGateway
from app.shared.contracts.embeddings import EmbeddingIndex
from app.shared.contracts.files import FilesApi
from app.shared.contracts.notebooks import NotebooksQueries
from app.shared.contracts.notify import TelegramSender
from app.shared.features import Feature, is_enabled
from app.shared.limits import EffectiveLimits
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker
from app.shared.wiring import ModuleDeps

import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)

ProcessName = Literal[
    "all", "identity", "api", "bot", "mail", "worker", "scheduler", "cli"
]


@dataclass(frozen=True, slots=True)
class ProcessPlan:
    """Which parts of the system a process builds."""

    emis: bool  # EMIS gateway, registration, Vault (identity-side secrets)
    in_process_emis_source: bool  # marks read EMIS through the local gateway
    files: bool
    mail: bool
    full: bool  # classwork, marks, flash cards, links, AI, notify, admin
    lms: bool
    # Holds the OpenRouter and Exa keys. False: the AI gateways are built without them
    # and fail only when called (the bot and one-off CLI commands such as create-user
    # build the AI module without the keys in their environment).
    ai_keys: bool = True


PLANS: dict[str, ProcessPlan] = {
    "all": ProcessPlan(True, True, True, True, True, True),
    "cli": ProcessPlan(True, True, True, True, True, True, ai_keys=False),
    # Files too: Administration sets profile photos (`/v1/admin/users/{id}/photo`).
    "identity": ProcessPlan(True, True, True, False, False, False),
    "api": ProcessPlan(False, False, True, True, True, True),
    "bot": ProcessPlan(False, False, True, True, True, False, ai_keys=False),
    "mail": ProcessPlan(False, False, True, True, False, False),
    # The worker destroys the Vault secret of deleted accounts.
    "worker": ProcessPlan(True, False, True, True, True, True),
    "scheduler": ProcessPlan(False, False, False, False, False, False),
}


@dataclass(frozen=True, slots=True)
class BuildOverrides:
    """Replacements for infrastructure that tests and local tools pass in."""

    clock: Clock | None = None
    redis: Redis | None = None
    hydra: HydraGateway | None = None
    credentials: CredentialStore | None = None
    email_sender: EmailSender | None = None
    telegram: TelegramSender | None = None
    llm: LlmGateway | None = None
    push: PushSender | None = None


def make_deps(container: Container) -> ModuleDeps:
    """The infrastructure every module's build() receives."""
    kicker = container.kicker

    async def kick_dispatch() -> None:
        await kicker.kick("notify.dispatch_due")

    async def roles_of(user_id: UUID) -> frozenset[Role]:
        user = await container.identity.directory.get_user(user_id)
        return user.roles if user is not None else frozenset()

    limits = EffectiveLimits(
        container.settings.limits,
        lambda: load_limit_snapshot(container.sessionmaker),
        today=lambda: local_today(container.clock),
        roles=roles_of,
    )
    container.limits = limits
    return ModuleDeps(
        settings=container.settings,
        clock=container.clock,
        redis=container.redis,
        sessionmaker=container.sessionmaker,
        kicker=kicker,
        rate_limiter=container.rate_limiter,
        i18n=container.i18n,
        outbox_writer=write_notifications,
        audit_writer=write_audit_events,
        outbox_committed_hook=kick_dispatch,
        limits=limits,
    )


class _Assembler:
    """Builds the modules of one container in dependency order."""

    def __init__(
        self, container: Container, plan: ProcessPlan, overrides: BuildOverrides
    ) -> None:
        self.container = container
        self.plan = plan
        self.overrides = overrides
        # Cycles (links ↔ flash cards, links ↔ AI, files ↔ links/AI) go through proxies.
        self.usage_links: LazyProxy[Any] = LazyProxy("links (files usage)")
        self.usage_ai: LazyProxy[Any] = LazyProxy("ai (files usage)")
        self.ai_proxy: LazyProxy[AiQueries] = LazyProxy("ai (links)")
        self.usage_notebooks: LazyProxy[Any] = LazyProxy("notebooks (files usage)")
        self.notebooks_proxy: LazyProxy[NotebooksQueries] = LazyProxy(
            "notebooks (links)"
        )
        # Identity stores profile photos in files, which needs the academic terms.
        self.files_proxy: LazyProxy[FilesApi] = LazyProxy("files (identity photos)")
        self.llm: LlmGateway | None = overrides.llm
        # Every model call is counted in the usage ledger (the decorators in ai).
        self.raw_llm: LlmGateway | None = overrides.llm
        # Set by build_embeddings (after the AI module); the AI module reads it late.
        self.embedding_index: EmbeddingIndex | None = None
        self.recorder = UsageRecorder(
            SqlUsageStore(container.sessionmaker), container.clock
        )
        self.deps = make_deps(container)

    def add_closer(self, closer: Callable[[], Awaitable[None]]) -> None:
        """Register something to close with the container."""
        self.container.closers.append(closer)

    def build(self) -> None:
        """Run every step the process needs."""
        self.build_telegram()
        self.build_identity_and_schedule()
        if self.plan.files:
            self.build_files()
        if self.plan.full:
            self.build_core()
        if self.plan.mail:
            self.build_mail()
        if self.plan.full:
            self.build_notify_and_admin()
            self.build_ai()
        if self.plan.lms:
            self.build_lms()
        if self.plan.full:
            self.build_library()
            self.build_notebooks()
            self.build_mcp_ports()

    # - - - Steps - - -

    def build_telegram(self) -> None:
        """TelegramSender: real or fake by TELEGRAM__MODE."""
        if self.overrides.telegram is not None:
            self.container.telegram = self.overrides.telegram
            return
        sender, closer = make_telegram_sender(
            self.container.settings, self.container.redis
        )
        self.container.telegram = sender
        if closer is not None:
            self.add_closer(closer)

    def build_identity_and_schedule(self) -> None:
        """Identity auth, the academic schedule, then EMIS (needs the enrollment)."""
        c = self.container
        hydra = self.overrides.hydra
        if hydra is None:
            admin = build_hydra_admin(c.settings)
            self.add_closer(admin.aclose)
            hydra = admin
        identity = build_identity(
            self.deps,
            files=self.files_proxy.view,
            hydra=hydra,
            telegram_sender=c.telegram,
            email_sender=self.overrides.email_sender,
        )
        c.identity = identity
        schedule = build_schedule(
            self.deps,
            identity=identity.directory,
            identity_commands=identity.commands,
        )
        c.academic = AcademicModule(schedule=schedule)
        if self.plan.emis:
            emis = identity.attach_emis(
                self.deps,
                academic_enrollment=schedule.enrollment,
                credentials=self.overrides.credentials,
            )
            self.add_closer(emis.close)

    def build_files(self) -> None:
        """Files; where files are used comes from links and AI (late bound)."""
        c = self.container
        schedule = c.academic.schedule
        usage = (
            UsageResolverAdapter(
                self.usage_links.view,
                self.usage_ai.view,
                self.usage_notebooks.view,
            )
            if self.plan.full
            else None
        )
        files = build_files(
            self.deps,
            terms=TermResolverAdapter(schedule.current_term, schedule.list_terms),
            usage=usage,
            sniffer=self.make_sniffer(),
        )
        c.files = files
        self.files_proxy.bind(files.public)
        self.add_closer(files.close)

    def make_sniffer(self) -> ContentSniffer | None:
        """libmagic, or in development a signature look-up when it is missing."""
        try:
            from app.modules.files.infrastructure.sniffing.magic_sniffer import (
                MagicSniffer,
            )

            return MagicSniffer()
        except ImportError:
            if self.container.settings.env == "prod":
                raise
            log.warning("libmagic_missing", fallback="SignatureSniffer")
            return SignatureSniffer()

    def build_core(self) -> None:
        """Flash cards, links, classwork and marks (links ↔ flash cards ↔ AI cycles)."""
        c = self.container
        schedule = c.academic.schedule
        identity = c.identity
        flashcards_links: LazyProxy[ShareResolver] = LazyProxy("links (flash cards)")
        flashcards = build_flashcards(self.deps, links=flashcards_links.view)
        links = build_links(
            self.deps,
            files=c.files.public,
            schedule=schedule.queries,
            identity=identity.directory,
            ai=self.ai_proxy.view,
            flashcards=flashcards.public,
            notebooks=self.notebooks_proxy.view,
        )
        flashcards_links.bind(links.public)
        self.usage_links.bind(links.public)
        c.flashcards = flashcards
        c.dashboard = build_dashboard(self.deps)
        c.links = links
        classwork = build_classwork(
            self.deps,
            identity=identity.directory,
            schedule=schedule.queries,
            links=links.public,
        )
        source, closer = make_emis_source(
            c.settings,
            gateway=identity.emis_services.gateway if identity.emis_services else None,
            in_process=self.plan.in_process_emis_source,
        )
        if closer is not None:
            self.add_closer(closer)
        emis_import = build_emis_import(
            self.deps,
            schedule=schedule,
            emis=source,
            identity=identity.directory,
            identity_commands=identity.commands,
            links=links.public,
            files=c.files.public,
        )
        marks = build_marks(
            self.deps,
            emis=source,
            identity=identity.directory,
            schedule=schedule.queries,
            identity_commands=identity.commands,
            enrollment=schedule.enrollment,
            links=links.public,
            bell_sync=emis_import.sync_class_hours,
            timetable_sync=emis_import.sync_group_timetable,
            material_resync=emis_import.sync_group_timetable,
        )
        c.academic = AcademicModule(
            schedule=schedule,
            classwork=classwork,
            marks=marks,
            emis_import=emis_import,
            assessments=build_assessments(
                self.deps, identity=identity.directory, schedule=schedule.queries
            ),
            teaching=build_teaching(
                self.deps,
                schedule=schedule.queries,
                identity=identity.directory,
                marks=marks.queries,
                classwork=classwork.queries,
            ),
        )

    def build_mail(self) -> None:
        """Mail; sending suspension is read from the identity user record."""
        try:
            from app.modules.mail.wiring import build as build_mail
        except ImportError:
            log.warning("module_not_available", module="mail")
            return
        c = self.container
        suspension = MailSuspensionAdapter(c.identity.auth.uow_factory, c.clock)
        c.mail = build_mail(
            self.deps,
            identity=c.identity.directory,
            files=c.files.public,
            suspension=suspension,
        )

    def build_notify_and_admin(self) -> None:
        """Notifications (bot renderers registered) and broadcasts."""
        c = self.container
        schedule = c.academic.schedule.queries
        c.notify = build_notify(
            self.deps,
            identity=c.identity.directory,
            schedule=schedule,
            links=c.links.public,
            mail=c.mail.public if c.mail is not None else cast(Any, None),
            files=c.files.public,
            telegram=c.telegram,
            push=self.overrides.push,
        )
        for closer in c.notify.closers:
            self.add_closer(closer)
        self.register_bot_renderers()
        c.admin = build_admin(
            self.deps, identity=c.identity.directory, schedule=schedule
        )

    def register_bot_renderers(self) -> None:
        """The bot module formats lesson prompts, mail and security notices."""
        try:
            from app.interfaces.bot.renderers import register_bot_renderers
        except ImportError:
            log.warning("module_not_available", module="bot renderers")
            return
        register_bot_renderers(self.container.notify.renderers, self.container)

    def build_ai(self) -> None:
        """The assistants; their Administration tools go through one adapter."""
        c = self.container
        tools = AdminToolBackendAdapter(c)
        c.admin_tools = tools
        self.raw_llm = self.overrides.llm or make_llm_gateway(
            c.settings, required=self.plan.ai_keys
        )
        self.llm = RecordingLlmGateway(self.raw_llm, self.recorder)
        c.llm = self.llm
        ai = build_ai(
            self.deps,
            llm=self.llm,
            identity=c.identity.directory,
            schedule=c.academic.schedule.queries,
            classwork=c.academic.classwork.queries,
            marks=c.academic.marks.queries,
            files=c.files.public,
            flashcards=c.flashcards.public,
            admin_tools=tools,
            links=c.links.public,
            web_search=RecordingWebSearch(
                make_web_search_gateway(
                    c.settings, c.redis, required=self.plan.ai_keys
                ),
                self.recorder,
            ),
            embeddings=lambda: self.embedding_index,
            free_usage=self.recorder,
        )
        ai.bindings.share_lookup = c.links.public
        self.ai_proxy.bind(ai.public)
        self.usage_ai.bind(ai.public)
        c.ai = ai

    def build_lms(self) -> None:
        """LMS authoring and learning."""
        c = self.container
        c.lms = build_lms(
            self.deps, identity=c.identity.directory, files=c.files.public
        )

    def build_library(self) -> None:
        """Library: books, materials and the UniLibrary base; before notebooks."""
        c = self.container
        c.library = build_library(
            self.deps,
            identity=c.identity.directory,
            files=c.files.public,
            academic=LibraryAcademicAdapter(c.academic.schedule, c.clock),
            lessons=LibraryLessonsAdapter(c.academic.schedule.queries, c.clock),
        )
        c.ai.bindings.library_search = LibraryPlatformSearch(
            c.library.catalogue.list_items
        )

    def build_embeddings(self) -> EmbeddingIndex | None:
        """The vectors module's index; None when search by meaning is switched off."""
        settings = self.container.settings
        if not is_enabled(settings, Feature.VECTOR_SEARCH):
            return None
        raw = self.raw_llm or make_llm_gateway(settings)
        gateway = RecordingEmbeddings(
            make_embedding_gateway(settings, raw), self.recorder
        )
        self.embedding_index = build_vectors(self.deps, gateway=gateway).index
        return self.embedding_index

    def build_notebooks(self) -> None:
        """Notebooks: built after AI and LMS; the assistant reaches it late-bound."""
        c = self.container
        llm = self.llm or self.overrides.llm or make_llm_gateway(c.settings)
        notebooks = build_notebooks(
            self.deps,
            llm=llm,
            identity=c.identity.directory,
            files=c.files.public,
            ai=c.ai.public,
            links=c.links.public,
            schedule=c.academic.schedule.queries,
            flashcards=c.flashcards.public,
            lms=c.lms.learning.source_reader if self.plan.lms else None,
            library=c.library.bridge.source_reader,
            library_queries=c.library.reader.queries,
            fetcher=HttpWebFetcher(),
            classwork=c.academic.classwork.queries,
            terms=NotebookTermsAdapter(c.academic.schedule.current_term),
            web_search=c.ai.web_search,
            workspace=c.lms.authoring.workspace if self.plan.lms else None,
            embeddings=self.build_embeddings(),
            lms_apply=(
                LmsApplyPorts(
                    workspace=c.lms.authoring.workspace_commands,
                    queries=c.lms.authoring.queries,
                    drafts=c.lms.authoring.draft_commands,
                )
                if self.plan.lms
                else None
            ),
        )
        c.ai.bindings.notebooks = notebooks.public
        c.ai.bindings.shared_search = SharedPlatformSearch(notebooks.shared_search)
        c.ai.bindings.notebooks_commands = notebooks.commands
        c.ai.bindings.documents = DocumentExporter()
        if self.plan.lms:  # the course author assistant (lms_author)
            authoring = c.lms.authoring
            c.ai.bindings.lms_workspace = authoring.workspace
            c.ai.bindings.lms_workspace_commands = authoring.workspace_commands
            c.ai.bindings.lms_queries = authoring.queries
            c.ai.bindings.lms_draft_commands = authoring.draft_commands
        self.usage_notebooks.bind(notebooks.public)
        self.notebooks_proxy.bind(notebooks.public)
        c.notebooks = notebooks

    def build_mcp_ports(self) -> None:
        """Ports the MCP servers need beyond the contracts."""
        c = self.container
        c.mcp_audit = McpAuditAdapter(c.sessionmaker)
        c.mcp_connector_courses = ConnectorCoursesAdapter(c.identity.auth.uow_factory)


async def build_container(
    settings: Settings,
    *,
    process: str,
    kicker: TaskKicker | None = None,
    overrides: BuildOverrides | None = None,
) -> Container:
    """Build the container for one process; modules the process does not need stay None.

    Without ``kicker`` tasks go to the taskiq broker, and the caller must have run
    ``await broker.startup()`` (the process bootstraps do).
    """
    plan = PLANS[process]
    if kicker is None:
        from app.interfaces.jobs.broker import TaskiqKicker, broker

        kicker = TaskiqKicker(broker)
    given = overrides or BuildOverrides()
    container = build_infrastructure(settings, kicker)
    if given.clock is not None:
        container.clock = given.clock
    if given.redis is not None:
        container.redis = given.redis
        container.rate_limiter = RateLimiter(given.redis)
    _Assembler(container, plan, given).build()
    log.info("container_built", process=process)
    return container
