"""The admission MCP server at `/mcp/admission` (personal tokens, students only)."""

from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol, TypeVar

from app.interfaces.mcp.admission.auth import AdmissionTokenVerifier
from app.interfaces.mcp.admission.tools import AdmissionMcpTools
from app.interfaces.mcp.auth import IhspAccessToken
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.endpoints import transport_security
from app.interfaces.mcp.errors import McpUnauthenticatedError
from app.interfaces.mcp.not_wired import NotWired
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.base_error import BaseError

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import AnyHttpUrl

INSTRUCTIONS: Final = (
    "Access to one student's own university application. Tools need the scope "
    "chosen when the personal token was created: admission:read (get_application, "
    "list_documents, list_memory_notes), admission:documents (read_document), "
    "admission:docs (upload_document) and admission:memory (write_memory_note, "
    "delete_memory_note). Memory notes are read by the in-app admission assistant."
)

_T = TypeVar("_T")


def admission_resource_url(settings: Settings) -> str:
    """Public URL of the admission MCP server."""
    return f"{settings.urls.mcp.rstrip('/')}/admission"


def build_admission_server(deps: McpDeps) -> FastMCP:
    """Create the server with its seven tools."""
    url = admission_resource_url(deps.settings)
    personal: Any = deps.personal_tokens or NotWired("personal_token_verifier")
    sniffer: Any = deps.sniffer or NotWired("content_sniffer")
    server = FastMCP(
        "Admission",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=transport_security(deps.settings),
        token_verifier=AdmissionTokenVerifier(
            access=deps.access_verifier,
            personal=personal,
            resource_url=url,
        ),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(deps.settings.hydra.issuer),
            resource_server_url=AnyHttpUrl(url),
            required_scopes=None,
            validate_token_resource=False,
        ),
    )
    tools = AdmissionMcpTools(
        deps.admission,
        deps.rate_limiter,
        deps.audit,
        sniffer=sniffer,
        consent=deps.consent,
    )
    call = _caller(deps)
    _register_read_tools(server, tools, call)
    _register_write_tools(server, tools, call)
    return server


class _Call(Protocol):
    async def __call__(self, fn: Callable[..., Awaitable[_T]], *args: Any) -> _T:
        """Run a tool method as the token's actor."""
        raise NotImplementedError


def _caller(deps: McpDeps) -> _Call:
    async def call(fn: Callable[..., Awaitable[_T]], *args: Any) -> _T:
        try:
            return await fn(_actor(), *args)
        except BaseError as error:
            text = deps.t(error.message_key, **error.params)
            raise ToolError(
                error.support_details if text == error.message_key else text
            ) from error

    return call


def _register_read_tools(
    server: FastMCP, tools: AdmissionMcpTools, call: _Call
) -> None:
    @server.tool()
    async def get_application() -> dict[str, Any]:
        """The student's profile, tasks, scores, universities and courses.

        Also activities and deadlines. Scope admission:read.
        """
        return await call(tools.get_application)

    @server.tool()
    async def list_documents() -> list[dict[str, Any]]:
        """The student's documents. Scope admission:read."""
        return await call(tools.list_documents)

    @server.tool()
    async def read_document(document_id: str) -> dict[str, Any]:
        """A download link (valid a few minutes) for one document.

        Scope admission:documents.
        """
        return await call(tools.read_document, document_id)

    @server.tool()
    async def list_memory_notes() -> list[dict[str, Any]]:
        """Notes saved for the admission assistant. Scope admission:read."""
        return await call(tools.list_memory_notes)


def _register_write_tools(
    server: FastMCP, tools: AdmissionMcpTools, call: _Call
) -> None:
    @server.tool()
    async def upload_document(
        kind: str, name: str, content_base64: str
    ) -> dict[str, Any]:
        """Upload a PDF, JPEG or PNG as a new document.

        `kind` is one of transcript, school_report, rec, certificate, passport,
        translation, test_report, bank, other. Scope admission:docs.
        """
        return await call(tools.upload_document, kind, name, content_base64)

    @server.tool()
    async def write_memory_note(content: str) -> dict[str, Any]:
        """Save a note (at most 4000 characters) for the admission assistant.

        Scope admission:memory.
        """
        return await call(tools.write_memory_note, content)

    @server.tool()
    async def delete_memory_note(note_id: str) -> dict[str, Any]:
        """Delete one memory note. Scope admission:memory."""
        return await call(tools.delete_memory_note, note_id)


def _actor() -> Actor:
    token = get_access_token()
    if not isinstance(token, IhspAccessToken):
        raise McpUnauthenticatedError()
    return token.actor
