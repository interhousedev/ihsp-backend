"""Memory notes and the admission MCP tools: scopes, ownership, expiry of access."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.mcp.admission.auth import AdmissionTokenVerifier
from app.interfaces.mcp.admission.tools import TOOL_SCOPES, AdmissionMcpTools
from app.interfaces.mcp.auth import IhspAccessToken
from app.interfaces.mcp.errors import McpNotFoundError, McpScopeError
from app.modules.admission.application.memory_notes import MemoryNoteService
from app.modules.admission.domain.documents import DocumentRecord
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.memory_notes import CONTENT_MAX, MemoryNote
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError, ForbiddenError, UnauthorizedError
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft
from tests.admission.unit.fakes import NOW, FakeStore, FakeUow
from tests.admission.unit.test_access_policy import OTHER, STUDENT, World
from tests.fakes.clock import FixedClock
from tests.fakes.files.sniffer import SignatureSniffer

import pytest

ALL = frozenset(set(TOOL_SCOPES.values()))
PDF = "JVBERi0xLjQKJSVFT0YK"  # "%PDF-1.4\n%%EOF\n"


class _Notes:
    def __init__(self) -> None:
        self.rows: dict[UUID, MemoryNote] = {}

    async def list_for(self, student_id: UUID) -> list[MemoryNote]:
        mine = [n for n in self.rows.values() if n.student_id == student_id]
        return sorted(mine, key=lambda n: n.created_at, reverse=True)

    async def count_for(self, student_id: UUID) -> int:
        return len(await self.list_for(student_id))

    async def get(self, note_id: UUID) -> MemoryNote | None:
        return self.rows.get(note_id)

    async def add(self, note: MemoryNote) -> None:
        self.rows[note.id] = note

    async def delete(self, note_id: UUID) -> None:
        self.rows.pop(note_id, None)


class _Uow(FakeUow):
    def __init__(self, s: FakeStore, notes: _Notes) -> None:
        super().__init__(s)
        self.memory_notes = notes


class _Docs:
    def __init__(self) -> None:
        self.mine = DocumentRecord(new_id(), STUDENT, "passport", "student", STUDENT)
        self.theirs = DocumentRecord(new_id(), OTHER, "passport", "student", OTHER)
        self.uploads: list[tuple[str, str, bytes]] = []

    async def listing(self, ctx: Any, student_id: UUID | None = None) -> list[Any]:
        docs = [d for d in (self.mine, self.theirs) if d.student_id == ctx.user_id]
        return [SimpleNamespace(doc=d, can_download=True) for d in docs]

    async def download(self, ctx: Any, doc_id: UUID) -> Any:
        return SimpleNamespace(url=f"https://s3/{doc_id}", expires_at=NOW)

    async def upload_limit(self, user_id: UUID) -> int:
        return 1024

    async def upload(self, ctx: Any, kind: str, name: str, data: bytes) -> Any:
        self.uploads.append((kind, name, data))
        return SimpleNamespace(doc=self.mine)


class _Audit:
    def __init__(self) -> None:
        self.drafts: list[AuditDraft] = []

    async def audit(self, draft: AuditDraft) -> None:
        self.drafts.append(draft)


class _Limiter:
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        return 1


class _Consent:
    def __init__(self) -> None:
        self.accepted = True
        self.calls: list[tuple[UUID, str]] = []

    async def execute(self, user_id: UUID, app: str = "global") -> None:
        self.calls.append((user_id, app))
        if not self.accepted:
            raise ForbiddenError()


class Kit:
    def __init__(self) -> None:
        self.w = World()
        self.notes = _Notes()
        self.docs = _Docs()
        self.audit = _Audit()
        self.consent = _Consent()
        self.service = MemoryNoteService(
            lambda: _Uow(self.w.store, self.notes), self.w.policy, FixedClock(NOW)
        )
        adm = SimpleNamespace(
            actor=self.w.resolver,
            documents=self.docs,
            memory_notes=self.service,
            application_data=None,
        )
        limiter: Any = _Limiter()
        self.tools = AdmissionMcpTools(
            adm, limiter, self.audit, sniffer=SignatureSniffer(), consent=self.consent
        )


def student(scopes: frozenset[str] = ALL, user: UUID = STUDENT) -> Actor:
    return Actor(user, frozenset({Role.STUDENT}), scopes=scopes)


# -- memory notes service ---------------------------------------------------


async def test_notes_are_owned_audited_and_limited() -> None:
    k = Kit()
    note = await k.service.add(await k.w.ctx(STUDENT, Role.STUDENT), " hi ", "app")
    assert note.content == "hi"
    assert [e.action for e in k.w.store.audit][-1] == "memory_note.created"
    other = await k.w.ctx(OTHER, Role.STUDENT)
    assert await k.service.list(other) == []
    with pytest.raises(AdmissionNotFoundError):
        await k.service.delete(other, note.id)
    assert note.id in k.notes.rows
    with pytest.raises(BaseError):
        await k.service.add(other, "x" * (CONTENT_MAX + 1), "app")
    with pytest.raises(BaseError):
        await k.service.add(other, "   ", "app")


# -- MCP tools ---------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(TOOL_SCOPES))
async def test_every_tool_needs_its_exact_scope(tool: str) -> None:
    k = Kit()
    others = ALL - {TOOL_SCOPES[tool]}
    args: dict[str, Any] = {
        "read_document": {"document_id": str(new_id())},
        "upload_document": {"kind": "passport", "name": "a.pdf", "content_base64": PDF},
        "write_memory_note": {"content": "x"},
        "delete_memory_note": {"note_id": str(new_id())},
    }.get(tool, {})
    with pytest.raises(McpScopeError):
        await getattr(k.tools, tool)(student(others), **args)
    assert k.audit.drafts[-1].type == "mcp.denied"
    assert k.audit.drafts[-1].metadata["tool"] == tool


async def test_tools_only_touch_the_callers_data() -> None:
    k = Kit()
    note = await k.tools.write_memory_note(student(), "remember SAT in May")
    assert k.audit.drafts[-1].type == "mcp.call"
    assert k.notes.rows[UUID(note["id"])].source == "mcp"
    intruder = student(user=OTHER)
    assert await k.tools.list_memory_notes(intruder) == []
    with pytest.raises(BaseError):
        await k.tools.delete_memory_note(intruder, note["id"])
    docs = await k.tools.list_documents(intruder)
    assert [d["id"] for d in docs] == [str(k.docs.theirs.id)]
    with pytest.raises(McpNotFoundError):
        await k.tools.read_document(intruder, str(k.docs.mine.id))
    link = await k.tools.read_document(student(), str(k.docs.mine.id))
    assert link["url"].endswith(str(k.docs.mine.id))


async def test_upload_checks_type_and_size() -> None:
    k = Kit()
    await k.tools.upload_document(student(), "passport", "a.pdf", PDF)
    assert k.docs.uploads[0][2].startswith(b"%PDF")
    with pytest.raises(BaseError):  # not a PDF/JPEG/PNG
        await k.tools.upload_document(student(), "passport", "a.txt", "aGVsbG8=")
    big = "JVBERi0" + "A" * 2001
    with pytest.raises(BaseError):
        await k.tools.upload_document(student(), "passport", "a.pdf", big)
    assert len(k.docs.uploads) == 1


async def test_read_document_needs_the_documents_scope() -> None:
    k = Kit()
    doc = str(k.docs.mine.id)
    with pytest.raises(McpScopeError):
        await k.tools.read_document(student(frozenset({"admission:read"})), doc)
    link = await k.tools.read_document(student(frozenset({"admission:documents"})), doc)
    assert link["url"].endswith(doc)


async def test_tools_require_admission_consent() -> None:
    k = Kit()
    k.consent.accepted = False
    with pytest.raises(ForbiddenError):
        await k.tools.list_documents(student())
    assert k.audit.drafts[-1].type == "mcp.denied"
    assert k.audit.drafts[-1].metadata["reason"] == "consent"
    assert k.consent.calls == [(STUDENT, "admission")]
    k.consent.accepted = True
    assert len(await k.tools.list_documents(student())) == 1


async def test_upload_type_is_sniffed_not_trusted() -> None:
    k = Kit()
    fake = "TVqQAAMAAAAEAAAA"  # an "MZ" executable named .pdf
    with pytest.raises(BaseError):
        await k.tools.upload_document(student(), "passport", "a.pdf", fake)
    assert k.docs.uploads == []


# -- token verifier ----------------------------------------------------------


class _Personal:
    def __init__(self, actor: Actor | None) -> None:
        self.actor = actor

    async def verify_personal(self, token: str) -> Actor:
        if self.actor is None:  # unknown, revoked or expired
            raise UnauthorizedError()
        return self.actor


class _Hydra:
    async def verify(self, token: str, *, audience: str) -> Actor:
        assert audience == "mcp-admission"
        return student()


def _verifier(actor: Actor | None) -> AdmissionTokenVerifier:
    return AdmissionTokenVerifier(
        access=_Hydra(),  # type: ignore[arg-type]
        personal=_Personal(actor),
        resource_url="https://mcp/admission",
    )


PAT = "ihsp_pat_" + "a" * 43


async def test_verifier_admits_students_with_an_admission_scope_only() -> None:
    ok = await _verifier(student()).verify_token(PAT)
    assert isinstance(ok, IhspAccessToken) and ok.actor.user_id == STUDENT
    assert await _verifier(None).verify_token(PAT) is None  # expired/revoked
    teacher = Actor(STUDENT, frozenset({Role.TEACHER}), scopes=ALL)
    assert await _verifier(teacher).verify_token(PAT) is None
    me_only = student(frozenset({"me:read"}))
    assert await _verifier(me_only).verify_token(PAT) is None
    assert await _verifier(None).verify_token("hydra-jwt") is not None


async def test_verifier_refuses_catalog_tokens() -> None:
    """ADM-INTL-3: an admission:catalog token never opens the MCP server."""
    catalog = frozenset({"admission:catalog"})
    counselor = Actor(STUDENT, frozenset({Role.COUNSELOR}), scopes=catalog)
    assert await _verifier(counselor).verify_token(PAT) is None
    assert await _verifier(student(catalog)).verify_token(PAT) is None
    assert await _verifier(student(ALL | catalog)).verify_token(PAT) is None
