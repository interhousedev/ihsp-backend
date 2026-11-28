"""Memory notes of the student's AI agent and how to connect it over MCP.

The student sees and deletes every note, whoever wrote it (the app, an MCP client
holding `admission:memory`, or the assistant). `GET /mcp/connection` tells the web
the URL of the admission MCP server, the token scopes and an example client
config; the student creates the personal token separately (off by default).
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.mcp.admission.server import admission_resource_url
from app.modules.admission.domain.memory_notes import CONTENT_MAX, MemoryNote
from app.modules.identity.domain.personal_token import (
    ADMISSION_MAX_EXPIRY_DAYS,
    ADMISSION_SCOPES,
)
from app.shared.mcp_scopes import scopes_for_roles

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class MemoryNoteIn(BaseModel):
    """A new note written in the app."""

    content: str = Field(min_length=1, max_length=CONTENT_MAX)


class MemoryNoteOut(BaseModel):
    """One note."""

    id: UUID
    content: str
    source: Literal["app", "mcp", "assistant"]
    created_at: datetime


class MemoryNoteListOut(BaseModel):
    """The caller's notes, newest first."""

    items: list[MemoryNoteOut]


class McpConnectionOut(BaseModel):
    """What the web shows on the "connect your AI agent" panel."""

    url: str
    scopes: list[str]
    max_expiry_days: int
    oauth_scopes: list[str] = Field(
        description="OAuth scopes of the admission server this caller's roles may hold"
    )
    app_url: str = Field(description="URL of the combined `/app` MCP server")
    connectors_url: str = Field(description="Page where the user connects AI services")
    example_config: dict[str, Any]


def _note(n: MemoryNote) -> MemoryNoteOut:
    return MemoryNoteOut(
        id=n.id, content=n.content, source=n.source, created_at=n.created_at
    )


@router.get(
    "/memory-notes",
    operation_id="admission_memory_notes_list",
    response_model=MemoryNoteListOut,
)
async def list_memory_notes(
    ctx: AdmissionCtx, container: ContainerDep
) -> MemoryNoteListOut:
    """The caller's memory notes."""
    notes = await container.admission.memory_notes.list(ctx)
    return MemoryNoteListOut(items=[_note(n) for n in notes])


@router.post(
    "/memory-notes",
    operation_id="admission_memory_notes_create",
    response_model=MemoryNoteOut,
    status_code=201,
)
async def create_memory_note(
    body: MemoryNoteIn, ctx: AdmissionCtx, container: ContainerDep
) -> MemoryNoteOut:
    """Save a note from the app."""
    note = await container.admission.memory_notes.add(ctx, body.content, "app")
    return _note(note)


@router.delete(
    "/memory-notes/{note_id}",
    operation_id="admission_memory_notes_delete",
    status_code=204,
)
async def delete_memory_note(
    note_id: UUID, ctx: AdmissionCtx, container: ContainerDep
) -> Response:
    """Delete one of the caller's notes."""
    await container.admission.memory_notes.delete(ctx, note_id)
    return Response(status_code=204)


@router.get(
    "/mcp/connection",
    operation_id="admission_mcp_connection",
    response_model=McpConnectionOut,
)
async def mcp_connection(
    ctx: AdmissionCtx, container: ContainerDep
) -> McpConnectionOut:
    """URL, scopes and an example config of the admission MCP server."""
    url = admission_resource_url(container.settings)
    return McpConnectionOut(
        url=url,
        scopes=sorted(ADMISSION_SCOPES),
        max_expiry_days=ADMISSION_MAX_EXPIRY_DAYS,
        oauth_scopes=sorted(scopes_for_roles("admission", ctx.actor.roles)),
        app_url=f"{container.settings.urls.mcp.rstrip('/')}/app",
        connectors_url=f"{container.settings.urls.id.rstrip('/')}/connectors/",
        example_config={
            "mcpServers": {
                "admission": {
                    "type": "http",
                    "url": url,
                    "headers": {"Authorization": "Bearer <personal token>"},
                }
            }
        },
    )
