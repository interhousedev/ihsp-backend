"""Everything the MCP servers consume, collected from the container."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.interfaces.mcp.constants import ERROR_LOCALE
from app.interfaces.mcp.links import McpLinks
from app.interfaces.mcp.not_wired import NotWired
from app.interfaces.mcp.ports import (
    ConnectorCoursesPort,
    McpAuditPort,
    McpFilesApi,
    McpScopeOverlayPort,
)
from app.settings import Settings
from app.shared.clock import Clock
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.ai import AdminToolBackend
from app.shared.contracts.auth import AccessTokenVerifier, ConnectorTokenVerifier
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import (
    LmsAiTools,
    LmsCourseOps,
    LmsDraftCommands,
    LmsQueries,
)
from app.shared.contracts.mcp_academic import McpAcademicTools
from app.shared.contracts.mcp_calls import McpCallLog
from app.shared.contracts.mcp_content import McpContentTools
from app.shared.contracts.mcp_files_courses import McpFilesCoursesTools
from app.shared.contracts.mcp_teacher import McpTeacherTools
from app.shared.contracts.teacher_ai import TeacherAiTools
from app.shared.i18n.core import I18nCore
from app.shared.limits import LimitsProvider, StaticLimits
from app.shared.rate_limit import RateLimiter

if TYPE_CHECKING:
    from app.bootstrap.container import Container


@dataclass(frozen=True, slots=True)
class McpDeps:
    """Services, settings and ports used by the tools of all the MCP servers."""

    settings: Settings
    clock: Clock
    rate_limiter: RateLimiter
    i18n: I18nCore
    audit: McpAuditPort
    connector_courses: ConnectorCoursesPort | None
    access_verifier: AccessTokenVerifier
    connector_verifier: ConnectorTokenVerifier
    schedule: ScheduleQueries
    classwork: ClassworkQueries
    marks: MarksQueries
    files: McpFilesApi
    links: LinksApi
    flashcards: FlashcardsApi
    lms_queries: LmsQueries
    lms_commands: LmsDraftCommands
    lms_ops: LmsCourseOps
    admin_tools: AdminToolBackend
    # The AI scopes revoked per user (cached): the guard refuses revoked users.
    limits: LimitsProvider
    call_log: McpCallLog
    # Scopes granted to a connector after its OAuth token was issued; None: no overlay.
    scope_overlay: McpScopeOverlayPort | None
    academic_tools: McpAcademicTools
    content_tools: McpContentTools
    files_courses_tools: McpFilesCoursesTools
    teacher_tools: McpTeacherTools
    # The model-backed teacher tools; None leaves them off the teacher server.
    teacher_ai: TeacherAiTools | None = None
    # The model-backed LMS drafting tools; None leaves them off the LMS server.
    lms_ai: LmsAiTools | None = None

    def t(self, key: str, **params: Any) -> str:  # noqa: ANN401 - i18n params
        """Translate a message key into the language of tool errors."""
        return self.i18n.t(ERROR_LOCALE, key, **params)

    @property
    def web_links(self) -> McpLinks:
        """Builders of our own links for tool results (`links.*`)."""
        return McpLinks(self.settings)


def deps_from_container(
    container: "Container",
    *,
    audit: McpAuditPort | None = None,
    admin_tools: AdminToolBackend | None = None,
    connector_courses: ConnectorCoursesPort | None = None,
) -> McpDeps:
    """Collect the dependencies of the MCP servers.

    Optional arguments fall back to container attributes of the same name (I1 sets
    `mcp_audit`, `admin_tools` and `mcp_connector_courses` on the container when it
    does not pass them). Audit and admin tools are required: the servers refuse to
    start without them instead of running unaudited.
    """
    audit = audit or getattr(container, "mcp_audit", None)
    admin_tools = admin_tools or getattr(container, "admin_tools", None)
    connector_courses = connector_courses or getattr(
        container, "mcp_connector_courses", None
    )
    call_log = getattr(container, "mcp_call_log", None)
    if audit is None or admin_tools is None or call_log is None:
        raise ValueError(
            "MCP servers need an audit port, a call log and an AdminToolBackend "
            "(pass audit= and admin_tools= or set container.mcp_audit, "
            "container.mcp_call_log and container.admin_tools)"
        )
    identity = container.identity
    return McpDeps(
        settings=container.settings,
        clock=container.clock,
        rate_limiter=container.rate_limiter,
        i18n=container.i18n,
        audit=audit,
        connector_courses=connector_courses,
        access_verifier=identity.token_verifier,
        connector_verifier=identity.connector_verifier,
        schedule=container.academic.schedule.queries,
        classwork=container.academic.classwork.queries,
        marks=container.academic.marks.queries,
        files=container.files.public,
        links=container.links.public,
        flashcards=container.flashcards.public,
        lms_queries=container.lms.authoring.queries,
        lms_commands=container.lms.authoring.draft_commands,
        lms_ops=container.lms.course_ops,
        admin_tools=admin_tools,
        limits=getattr(container, "limits", None)
        or StaticLimits(container.settings.limits),
        call_log=call_log,
        scope_overlay=getattr(container, "mcp_scope_overlay", None),
        academic_tools=_backend(container, "mcp_academic_tools"),
        content_tools=_backend(container, "mcp_content_tools"),
        files_courses_tools=_backend(container, "mcp_files_courses_tools"),
        teacher_tools=_backend(container, "mcp_teacher_tools"),
        teacher_ai=getattr(container, "teacher_ai_tools", None),
        lms_ai=getattr(container, "lms_ai_tools", None),
    )


def _backend(container: "Container", name: str) -> Any:  # noqa: ANN401 - a protocol
    return getattr(container, name, None) or NotWired(name)
