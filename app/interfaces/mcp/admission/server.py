"""The admission MCP server at `/mcp/admission`: applicant and staff tools.

Built like every role server (Hydra and connector tokens), plus `ihsp_pat_`
personal tokens of students through `PersonalTokenVerifier`. Each tool narrows
the server roles with its own `roles`.
"""

from typing import Any

from app.interfaces.mcp.admission.auth import PersonalTokenVerifier
from app.interfaces.mcp.admission.tools import TOOL_MODULES
from app.interfaces.mcp.admission.tools.staff import register_staff
from app.interfaces.mcp.catalog import CatalogMcp
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import finish_catalog, make_toolkit
from app.interfaces.mcp.not_wired import NotWired
from app.settings import Settings
from app.shared.brand import current_brand

from mcp.server.fastmcp import FastMCP

PINNED = ["get_application", "get_today", "list_caseload"]


def admission_resource_url(settings: Settings) -> str:
    """Public URL of the admission MCP server."""
    return f"{settings.urls.mcp.rstrip('/')}/admission"


def build_admission_server(deps: McpDeps) -> FastMCP:
    """Create the admission server with its applicant and staff tools."""
    kit = make_toolkit(
        deps,
        "admission",
        title=f"{current_brand().name} Admission",
        instructions_key="mcp-instructions-admission",
        cls=CatalogMcp,
    )
    for module in TOOL_MODULES:
        module.register(kit)
    register_staff(kit)
    finish_catalog(kit, "admission", PINNED)
    personal: Any = deps.personal_tokens or NotWired("personal_token_verifier")
    inner = kit.mcp._token_verifier
    assert inner is not None
    kit.mcp._token_verifier = PersonalTokenVerifier(
        inner=inner,
        personal=personal,
        resource_url=admission_resource_url(deps.settings),
    )
    return kit.mcp
