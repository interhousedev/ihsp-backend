"""Memory-note tools: notes the in-app admission assistant reads as context."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admission.tools.common import applicant, services
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.domain.memory_notes import CONTENT_MAX, MemoryNote
from app.shared.mcp_scopes import ADMISSION_APPLICANT_ROLES

from pydantic import Field

ROLES = ADMISSION_APPLICANT_ROLES


def _note(n: MemoryNote) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "content": n.content,
        "source": n.source,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def register(kit: ToolKit) -> None:
    """Register the memory tools."""

    @kit.tool("memory:read", roles=ROLES)  # type: ignore[type-var]  # returns a list
    async def list_memory_notes() -> list[dict[str, Any]]:
        """The notes saved for the admission assistant, newest first."""
        ctx = await applicant(kit)
        return [_note(n) for n in await services(kit).memory_notes.list(ctx)]

    @kit.tool(
        "memory:write",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(),
        roles=ROLES,
    )
    async def write_memory_note(
        content: Annotated[
            str,
            Field(
                min_length=1,
                max_length=CONTENT_MAX,
                description="The note: a fact the admission assistant should remember.",
            ),
        ],
    ) -> dict[str, Any]:
        """Save a note for the admission assistant; it reads it as context."""
        ctx = await applicant(kit)
        return _note(await services(kit).memory_notes.add(ctx, content, "mcp"))

    @kit.tool(
        "memory:write",
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("note_id",)),
        roles=ROLES,
    )
    async def delete_memory_note(
        note_id: Annotated[UUID, Field(description="Id of one of the caller's notes.")],
    ) -> dict[str, Any]:
        """Delete one of the caller's memory notes."""
        ctx = await applicant(kit)
        await services(kit).memory_notes.delete(ctx, note_id, "mcp")
        return {"deleted": str(note_id)}
