"""Tool: write an Office document (.docx, .xlsx, .pptx) into the user's files."""

from typing import Any, Literal

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope

from pydantic import Field

CONTENT_MAX_CHARS = 60_000
_STAFF_ROLES = frozenset({Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN, Role.LMS_CREATOR})


class MakeDocumentArgs(ToolArgs):
    """The kind, the title and the text of the document."""

    kind: Literal["docx", "xlsx", "pptx"]
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=CONTENT_MAX_CHARS)


class MakeDocument(ReadTool[MakeDocumentArgs]):
    """Stores a generated document as the user's own file."""

    name = "make_document"
    description = (
        "Create a downloadable file in the user's My files and show it in the chat. "
        "kind docx: content is Markdown (# headings, - lists, | tables |, LaTeX stays "
        "as text). kind xlsx: content is one table, Markdown or CSV, header row "
        "first. kind pptx: content is a slide outline: a '# Title' line and '- ' "
        "bullets per slide, slides separated by a line '---', optional 'Notes: ...' "
        "line for speaker notes. Do not paste the file text again in your answer."
    )
    args_model = MakeDocumentArgs

    def __init__(self, files: FilesApi, bindings: LateBindings) -> None:
        """Store the files API and the late-bound document renderer."""
        self.files = files
        self.bindings = bindings

    async def run(self, args: MakeDocumentArgs, ctx: ToolContext) -> dict[str, Any]:
        """Render the document, store it for the user and return the file card."""
        renderer = self.bindings.documents
        if renderer is None:
            raise ToolFailedError(support_details="documents are unavailable")
        document = renderer.render(args.kind, args.title, args.content)
        ref = await self.files.store_bytes(
            owner_id=ctx.actor.user_id,
            scope=scope_of(ctx.actor),
            purpose=FilePurpose.AI_UPLOAD,
            name=document.name,
            data=document.data,
        )
        return {
            "file_id": str(ref.id),
            "name": ref.name,
            "kind": args.kind,
            "size": ref.byte_size,
        }


def scope_of(actor: Actor) -> FileScope:
    """Staff files count against the staff quota, students' against theirs."""
    return FileScope.STAFF if _STAFF_ROLES & actor.roles else FileScope.STUDENT
