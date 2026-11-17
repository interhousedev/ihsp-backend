"""Tools of the admission MCP server, free of the SDK so they can be unit-tested.

Every tool needs its exact scope on the token, reads or writes only the caller's
own data (the student id always comes from the token, never from arguments), is
rate-limited per user and leaves an audit record (`mcp.call` or `mcp.denied`).
"""

import datetime as dt
from typing import Any, Final, get_args
from uuid import UUID

from app.interfaces.mcp.constants import CALLS_PER_MINUTE
from app.interfaces.mcp.errors import (
    McpInvalidInputError,
    McpNotFoundError,
    McpRateLimitedError,
    McpScopeError,
)
from app.interfaces.mcp.ports import McpAuditPort
from app.interfaces.mcp.upload_file import decode_base64
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.documents import UPLOAD_MIME
from app.modules.admission.domain.workflow import DocumentKind
from app.modules.files.domain.errors import FileTooLargeError, TypeNotAllowedError
from app.modules.files.domain.policy import SNIFF_BYTES
from app.modules.files.ports.content_sniffer import ContentSniffer
from app.modules.identity.domain.personal_token import PersonalTokenScope
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError, RateLimitedError
from app.shared.contracts.legal import ConsentGate
from app.shared.notifications import AuditDraft
from app.shared.rate_limit import RateLimiter

READ: Final = PersonalTokenScope.ADMISSION_READ.value
MEMORY: Final = PersonalTokenScope.ADMISSION_MEMORY.value
DOCS: Final = PersonalTokenScope.ADMISSION_DOCS.value
DOCUMENTS: Final = PersonalTokenScope.ADMISSION_DOCUMENTS.value
# The legal documents the HTTP admission routes require (`/v1/admission` scope).
CONSENT_APP: Final = "admission"

# tool name -> the one scope it needs
TOOL_SCOPES: Final[dict[str, str]] = {
    "get_application": READ,
    "list_documents": READ,
    "read_document": DOCUMENTS,
    "list_memory_notes": READ,
    "upload_document": DOCS,
    "write_memory_note": MEMORY,
    "delete_memory_note": MEMORY,
}

_KINDS: Final = frozenset(get_args(DocumentKind))


class AdmissionMcpTools:
    """The seven tools; `actor` is the verified token owner."""

    def __init__(
        self,
        admission: Any,  # noqa: ANN401 - AdmissionServices
        rate_limiter: RateLimiter,
        audit: McpAuditPort,
        *,
        sniffer: ContentSniffer,
        consent: ConsentGate | None,
    ) -> None:
        """Keep the services, limiter, audit port, content sniffer and consent gate."""
        self._adm = admission
        self._limiter = rate_limiter
        self._audit = audit
        self._sniffer = sniffer
        self._consent = consent

    # -- guard -----------------------------------------------------------

    async def _enter(
        self, actor: Actor, tool: str, meta: dict[str, Any]
    ) -> AdmissionContext:
        scope = TOOL_SCOPES[tool]
        if scope not in actor.scopes:
            denial = {"reason": "scope", "scope": scope}
            await self._record(actor, "mcp.denied", tool, denial)
            raise McpScopeError(params={"scope": scope})
        if not actor.has(Role.STUDENT):
            await self._record(actor, "mcp.denied", tool, {"reason": "role"})
            raise ForbiddenError()
        await self._check_consent(actor, tool)
        try:
            await self._limiter.hit(
                f"mcp:admission:{actor.user_id}",
                limit=CALLS_PER_MINUTE,
                window_seconds=60,
            )
        except RateLimitedError as error:
            await self._record(actor, "mcp.denied", tool, {"reason": "rate"})
            raise McpRateLimitedError(params=error.params) from error
        ctx: AdmissionContext = await self._adm.actor.execute(actor)
        if not ctx.admission.may_enter:
            await self._record(actor, "mcp.denied", tool, {"reason": "not-entitled"})
            raise ForbiddenError()
        await self._record(actor, "mcp.call", tool, meta)
        return ctx

    async def _check_consent(self, actor: Actor, tool: str) -> None:
        if self._consent is None:
            return
        try:
            await self._consent.execute(actor.user_id, CONSENT_APP)
        except ForbiddenError:
            await self._record(actor, "mcp.denied", tool, {"reason": "consent"})
            raise

    async def _record(
        self, actor: Actor, kind: str, tool: str, extra: dict[str, Any]
    ) -> None:
        await self._audit.audit(
            AuditDraft(
                type=kind,
                user_id=actor.user_id,
                actor_id=actor.user_id,
                metadata={"server": "admission", "tool": tool, **extra},
            )
        )

    # -- read ------------------------------------------------------------

    async def get_application(self, actor: Actor) -> dict[str, Any]:
        """Profile, tasks, activities, scores, universities, deadlines, courses."""
        ctx = await self._enter(actor, "get_application", {})
        data, me = self._adm.application_data, ctx.user_id
        return {
            "profile": await data.profile(me),
            "tasks": await data.tasks(me),
            "activities": await data.items(me),
            "test_scores": await data.test_scores(me),
            "universities": await data.universities(me),
            "deadlines": await data.deadlines(me),
            "courses": await data.courses(me),
        }

    async def list_documents(self, actor: Actor) -> list[dict[str, Any]]:
        """The caller's documents with their versions."""
        ctx = await self._enter(actor, "list_documents", {})
        views = await self._adm.documents.listing(ctx)
        return [
            {
                "id": str(v.doc.id),
                "kind": v.doc.kind,
                "review_status": v.doc.review_status,
                "current_version": v.doc.current_version,
                "can_download": v.can_download,
                "created_at": _iso(v.doc.created_at),
            }
            for v in views
            if v.doc.student_id == ctx.user_id
        ]

    async def read_document(self, actor: Actor, document_id: str) -> dict[str, Any]:
        """A short-lived download link for one of the caller's documents."""
        doc_id = _uuid(document_id)
        ctx = await self._enter(actor, "read_document", {"document_id": str(doc_id)})
        await self._own_document(ctx, doc_id)
        link = await self._adm.documents.download(ctx, doc_id)
        return {"url": link.url, "expires_at": link.expires_at.isoformat()}

    async def list_memory_notes(self, actor: Actor) -> list[dict[str, Any]]:
        """The caller's memory notes, newest first."""
        ctx = await self._enter(actor, "list_memory_notes", {})
        return [_note(n) for n in await self._adm.memory_notes.list(ctx)]

    # -- write -----------------------------------------------------------

    async def upload_document(
        self, actor: Actor, kind: str, name: str, content_base64: str
    ) -> dict[str, Any]:
        """Upload a new document (PDF, JPEG or PNG within the admin-set size)."""
        if kind not in _KINDS:
            reason = f"kind must be one of {', '.join(sorted(_KINDS))}"
            raise McpInvalidInputError(params={"reason": reason})
        ctx = await self._enter(actor, "upload_document", {"kind": kind})
        file_name, data = decode_base64(content_base64, name)
        limit = await self._adm.documents.upload_limit(ctx.user_id)
        if len(data) > limit:
            raise FileTooLargeError(params={"max_mb": round(limit / (1024 * 1024), 1)})
        if await self._sniffer.sniff(data[:SNIFF_BYTES]) not in UPLOAD_MIME:
            raise TypeNotAllowedError(params={"types": ", ".join(UPLOAD_MIME)})
        view = await self._adm.documents.upload(ctx, kind, file_name, data)
        return {"id": str(view.doc.id), "kind": view.doc.kind}

    async def write_memory_note(self, actor: Actor, content: str) -> dict[str, Any]:
        """Save a note the admission assistant will read as context."""
        ctx = await self._enter(actor, "write_memory_note", {})
        return _note(await self._adm.memory_notes.add(ctx, content, "mcp"))

    async def delete_memory_note(self, actor: Actor, note_id: str) -> dict[str, Any]:
        """Delete one of the caller's notes."""
        nid = _uuid(note_id)
        ctx = await self._enter(actor, "delete_memory_note", {"note_id": str(nid)})
        await self._adm.memory_notes.delete(ctx, nid, "mcp")
        return {"deleted": str(nid)}

    async def _own_document(self, ctx: AdmissionContext, doc_id: UUID) -> None:
        views = await self._adm.documents.listing(ctx)
        mine = (v.doc for v in views if v.doc.student_id == ctx.user_id)
        if not any(d.id == doc_id for d in mine):
            raise McpNotFoundError()


def _uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise McpInvalidInputError(params={"reason": "not a valid id"}) from exc


def _note(n: Any) -> dict[str, Any]:  # noqa: ANN401 - MemoryNote
    return {
        "id": str(n.id),
        "content": n.content,
        "source": n.source,
        "created_at": _iso(n.created_at),
    }


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None
