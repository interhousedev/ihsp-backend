"""Document tools: the caller's admission documents and certificate proofs.

Uploads are sniffed (PDF, JPEG or PNG only) and capped at the admin-set size before
anything is stored; a stored proof file is owned by the caller.
"""

from typing import Annotated, Any, get_args
from uuid import UUID

from app.interfaces.mcp.admission.tools.common import (
    ItemId,
    applicant,
    lazy_services,
    services,
)
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.errors import McpInvalidInputError, McpNotFoundError
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.upload_file import decode_base64
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.documents import UPLOAD_MIME
from app.modules.admission.domain.workflow import DocumentKind
from app.modules.files.domain.errors import FileTooLargeError, TypeNotAllowedError
from app.modules.files.domain.policy import SNIFF_BYTES
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.mcp_scopes import ADMISSION_APPLICANT_ROLES

from pydantic import Field

ROLES = ADMISSION_APPLICANT_ROLES
DocumentId = Annotated[UUID, Field(description="Id from list_documents.")]
FileName = Annotated[
    str, Field(min_length=1, max_length=200, description="File name with extension.")
]
Content = Annotated[str, Field(description="The file, base64-encoded.")]


async def _checked_bytes(
    kit: ToolKit, ctx: AdmissionContext, name: str, content_base64: str
) -> tuple[str, bytes]:
    """Decode an upload; refuse it when too large or not a PDF, JPEG or PNG."""
    file_name, data = decode_base64(content_base64, name)
    limit = await services(kit).documents.upload_limit(ctx.user_id)
    if len(data) > limit:
        raise FileTooLargeError(params={"max_mb": round(limit / (1024 * 1024), 1)})
    sniffer = kit.deps.sniffer
    if sniffer is None:
        raise RuntimeError("the content sniffer is not wired into the MCP server")
    if await sniffer.sniff(data[:SNIFF_BYTES]) not in UPLOAD_MIME:
        raise TypeNotAllowedError(params={"types": ", ".join(UPLOAD_MIME)})
    return file_name, data


def register(kit: ToolKit) -> None:  # noqa: C901 - one closure per tool
    """Register the document tools."""
    adm = lazy_services(kit)

    @kit.tool("documents:read", roles=ROLES)
    async def list_documents() -> dict[str, Any]:
        """The student's documents with their review status and versions."""
        ctx = await applicant(kit)
        views = await adm.documents.listing(ctx)
        return {
            "items": [
                {
                    "id": str(v.doc.id),
                    "kind": v.doc.kind,
                    "review_status": v.doc.review_status,
                    "current_version": v.doc.current_version,
                    "can_download": v.can_download,
                    "created_at": v.doc.created_at,
                }
                for v in views
                if v.doc.student_id == ctx.user_id
            ]
        }

    @kit.tool(
        "documents:read",
        read_only=True,
        idempotent=False,
        log=LogSpec(keep=("document_id",)),
        roles=ROLES,
    )
    async def read_document(document_id: DocumentId) -> dict[str, Any]:
        """A short-lived download link (5 minutes) for one of the documents."""
        ctx = await applicant(kit)
        views = await adm.documents.listing(ctx)
        if not any(
            v.doc.id == document_id and v.doc.student_id == ctx.user_id for v in views
        ):
            raise McpNotFoundError()
        link = await adm.documents.download(ctx, document_id)
        return {"url": link.url, "expires_at": link.expires_at}

    @kit.tool(
        "documents:write",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("kind",)),
        roles=ROLES,
    )
    async def upload_document(
        kind: Annotated[
            DocumentKind,
            Field(description=f"One of {', '.join(get_args(DocumentKind))}."),
        ],
        name: FileName,
        content_base64: Content,
    ) -> dict[str, Any]:
        """Upload a new document (PDF, JPEG or PNG within the admin-set size)."""
        ctx = await applicant(kit)
        file_name, data = await _checked_bytes(kit, ctx, name, content_base64)
        view = await adm.documents.upload(ctx, kind, file_name, data)
        return {"id": str(view.doc.id), "kind": view.doc.kind}

    @kit.tool(
        "documents:write",
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("item_id",)),
        roles=ROLES,
    )
    async def add_certificate_proof(
        item_id: ItemId,
        url: Annotated[
            str | None, Field(max_length=2000, description="A public link to check.")
        ] = None,
        pasted_text: Annotated[
            str | None, Field(max_length=20000, description="The certificate text.")
        ] = None,
        name: FileName | None = None,
        content_base64: Content | None = None,
    ) -> dict[str, Any]:
        """Attach a proof to an activity or honor: a link, a text or a file.

        Give exactly one of `url`, `pasted_text` or `content_base64` (with `name`).
        Links are checked for reachability.
        """
        ctx = await applicant(kit)
        if sum(v is not None for v in (url, pasted_text, content_base64)) != 1:
            raise McpInvalidInputError(
                params={"reason": "give one of url, pasted_text, content_base64"}
            )
        views = await adm.items.list_items(ctx, ctx.user_id)
        if not any(v.item.id == item_id for v in views):
            raise McpNotFoundError()
        file_id: UUID | None = None
        if content_base64 is not None:
            file_name, data = await _checked_bytes(kit, ctx, name or "", content_base64)
            ref = await kit.deps.files.store_bytes(
                owner_id=ctx.user_id,
                scope=FileScope.STUDENT,
                purpose=FilePurpose.ADMISSION_DOCUMENT,
                name=file_name,
                data=data,
            )
            file_id = ref.id
        res = await adm.proofs.add(
            ctx, item_id, url=url, file_id=file_id, pasted_text=pasted_text
        )
        return {"proof": res.proof, "title": res.title}
