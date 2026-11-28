"""Memory notes, the admission memory tools and the personal-token verifier."""

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

from app.interfaces.mcp import guard as guard_module
from app.interfaces.mcp.admission.auth import PersonalTokenVerifier
from app.interfaces.mcp.admission.tools import memory
from app.interfaces.mcp.auth import IhspAccessToken
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.guard import ToolGuard
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.application.memory_notes import MemoryNoteService
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.memory_notes import CONTENT_MAX, MemoryNote
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError, UnauthorizedError
from app.shared.mcp_scopes import pat_scopes
from tests.admission.unit.fakes import NOW, FakeStore, FakeUow
from tests.admission.unit.test_access_policy import OTHER, STUDENT, World
from tests.fakes.clock import FixedClock

import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

OLD = frozenset({"admission:read", "admission:memory"})
ALL = pat_scopes(OLD)


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


async def _noop(*a: Any, **k: Any) -> None:  # noqa: ANN401
    return None


async def _ready(value: Any) -> Any:  # noqa: ANN401
    return value


class Kit:
    def __init__(self) -> None:
        self.w = World()
        self.notes = _Notes()
        self.service = MemoryNoteService(
            lambda: _Uow(self.w.store, self.notes), self.w.policy, FixedClock(NOW)
        )
        admission = SimpleNamespace(actor=self.w.resolver, memory_notes=self.service)
        deps = SimpleNamespace(
            t=lambda key, **p: key,
            maintenance=None,
            rate_limiter=SimpleNamespace(hit=_noop),
            consent=None,
            scope_overlay=None,
            limits=SimpleNamespace(
                ai_access=lambda _u: _ready(SimpleNamespace(blocks=lambda _s: False))
            ),
            audit=SimpleNamespace(audit=_noop),
            call_log=SimpleNamespace(record=_noop),
            admission=admission,
        )
        self.mcp = FastMCP("t")
        guard = ToolGuard(cast(McpDeps, deps), "admission")
        memory.register(ToolKit(self.mcp, cast(McpDeps, deps), guard))
        self.actor = student()

    async def call(self, name: str, **kwargs: Any) -> Any:  # noqa: ANN401
        fn = cast(
            Callable[..., Awaitable[Any]],
            self.mcp._tool_manager.get_tool(name).fn,  # type: ignore[union-attr]
        )
        with patch.object(guard_module, "_token_actor", lambda: self.actor):
            return await fn(**kwargs)


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


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("list_memory_notes", {}),
        ("write_memory_note", {"content": "x"}),
        ("delete_memory_note", {"note_id": STUDENT}),
    ],
)
async def test_every_memory_tool_needs_a_scope(tool: str, args: dict[str, Any]) -> None:
    k = Kit()
    k.actor = student(frozenset())
    with pytest.raises(ToolError):
        await k.call(tool, **args)


async def test_tools_only_touch_the_callers_notes() -> None:
    k = Kit()
    note = await k.call("write_memory_note", content="remember SAT in May")
    assert k.notes.rows[UUID(note["id"])].source == "mcp"
    listed = (await k.call("list_memory_notes"))["result"]
    assert [n["id"] for n in listed] == [note["id"]]
    k.actor = student(user=OTHER)
    assert (await k.call("list_memory_notes"))["result"] == []
    with pytest.raises(ToolError):
        await k.call("delete_memory_note", note_id=UUID(note["id"]))
    assert UUID(note["id"]) in k.notes.rows


async def test_staff_cannot_use_applicant_memory_tools() -> None:
    k = Kit()
    k.actor = Actor(STUDENT, frozenset({Role.COUNSELOR}), scopes=ALL)
    with pytest.raises(ToolError):
        await k.call("list_memory_notes")


# -- token verifier ----------------------------------------------------------


class _Personal:
    def __init__(self, actor: Actor | None) -> None:
        self.actor = actor

    async def verify_personal(self, token: str) -> Actor:
        if self.actor is None:  # unknown, revoked or expired
            raise UnauthorizedError()
        return self.actor


class _Inner:
    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id="hydra", scopes=[])


def _verifier(actor: Actor | None) -> PersonalTokenVerifier:
    return PersonalTokenVerifier(
        inner=_Inner(),
        personal=_Personal(actor),
        resource_url="https://mcp/admission",
    )


PAT = "ihsp_pat_" + "a" * 43


async def test_verifier_admits_students_with_an_admission_scope_only() -> None:
    ok = await _verifier(student(OLD)).verify_token(PAT)
    assert isinstance(ok, IhspAccessToken) and ok.actor.user_id == STUDENT
    assert ok.actor.scopes == ALL
    assert await _verifier(None).verify_token(PAT) is None  # expired/revoked
    teacher = Actor(STUDENT, frozenset({Role.TEACHER}), scopes=OLD)
    assert await _verifier(teacher).verify_token(PAT) is None
    me_only = student(frozenset({"me:read"}))
    assert await _verifier(me_only).verify_token(PAT) is None
    other = await _verifier(None).verify_token("hydra-jwt")
    assert other is not None and other.client_id == "hydra"


async def test_verifier_refuses_catalog_tokens() -> None:
    """ADM-INTL-3: an admission:catalog token never opens the MCP server."""
    catalog = frozenset({"admission:catalog"})
    counselor = Actor(STUDENT, frozenset({Role.COUNSELOR}), scopes=catalog)
    assert await _verifier(counselor).verify_token(PAT) is None
    assert await _verifier(student(catalog)).verify_token(PAT) is None
    assert await _verifier(student(OLD | catalog)).verify_token(PAT) is None
