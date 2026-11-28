"""Document review: accept or reject one student document."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.admission.sharing import (
    servable_document,
    shareable,
    staff_context,
)
from app.interfaces.mcp.admission.tools.common import lazy_services
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.errors import McpNotFoundError
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.domain.documents import REJECT_NOTE_LIMIT
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.shared.mcp_scopes import ADMISSION_STAFF_ROLES

from pydantic import Field

ReasonCode = Literal["illegible", "wrong_document", "expired", "other"]


def register(kit: ToolKit) -> None:
    """Register the review tool."""
    adm = lazy_services(kit)

    @kit.tool(
        "documents:review",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("student_id", "document_id", "accept", "reason_code")),
        roles=ADMISSION_STAFF_ROLES,
    )
    async def review_document(
        student_id: Annotated[UUID, Field(description="Owner of the document.")],
        document_id: Annotated[UUID, Field(description="From list_document_queue.")],
        accept: Annotated[bool, Field(description="True accepts, False rejects.")],
        reason_code: Annotated[
            ReasonCode | None, Field(description="Required when rejecting.")
        ] = None,
        note: Annotated[str | None, Field(max_length=REJECT_NOTE_LIMIT)] = None,
    ) -> dict[str, Any]:
        """Accept or reject a student's document; the student is told the outcome.

        Recommendation letters and bank documents cannot be reviewed here.
        """
        ctx = await staff_context(kit)
        if not (await adm.access.resolve(ctx, student_id)).in_scope:
            raise AdmissionNotFoundError()
        if (hidden := await shareable(kit, ctx, student_id)) is not None:
            return hidden
        views = await adm.documents.listing(ctx, student_id)
        if not any(v.doc.id == document_id and servable_document(v) for v in views):
            raise McpNotFoundError()
        done = await adm.documents.review(
            ctx, document_id, accept=accept, reason_code=reason_code, note=note
        )
        return {
            "document_id": str(done.doc.id),
            "review_status": done.doc.review_status,
            "reject_reason_code": done.doc.reject_reason_code,
        }
