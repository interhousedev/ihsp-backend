"""Applicant tools of the admission server: own data only, uploads, scopes, roles."""

import base64
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

from app.interfaces.mcp import guard as guard_module
from app.interfaces.mcp.admission.tools import application, catalog, documents
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.guard import ToolGuard
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.ids import new_id

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

ME, OTHER, COUNSELOR = new_id(), new_id(), new_id()
SCOPES = frozenset(
    {
        "application:read",
        "application:write",
        "documents:read",
        "documents:write",
        "catalog:read",
        "consents:read",
    }
)
PDF = b"%PDF-1.7\n" + b"x" * 64


def _item(owner: UUID) -> SimpleNamespace:
    return SimpleNamespace(item=SimpleNamespace(id=new_id(), student_id=owner))


def _doc(owner: UUID) -> SimpleNamespace:
    doc = SimpleNamespace(
        id=new_id(),
        student_id=owner,
        kind="passport",
        review_status="none",
        current_version=1,
        created_at=None,
    )
    return SimpleNamespace(doc=doc, can_download=True)


async def _noop(*a: Any, **k: Any) -> None:  # noqa: ANN401
    return None


async def _ready(value: Any) -> Any:  # noqa: ANN401
    return value


class Fixture:
    """Two students' data in fakes that, like the real services, filter by caller."""

    def __init__(self) -> None:  # noqa: C901 - one fake closure per service
        self.items = {ME: [_item(ME)], OTHER: [_item(OTHER)]}
        self.scores = {u: [SimpleNamespace(id=new_id())] for u in (ME, OTHER)}
        self.docs = {ME: [_doc(ME)], OTHER: [_doc(OTHER)]}
        self.calls: list[tuple[str, Any]] = []
        self.stored: list[dict[str, Any]] = []
        self.sniffed = "application/pdf"
        self.limit = 1024
        f = self

        async def resolve(actor: Actor) -> SimpleNamespace:
            student = actor.has(Role.STUDENT)
            return SimpleNamespace(
                user_id=actor.user_id,
                admission=SimpleNamespace(is_applicant=student, is_staff=not student),
            )

        async def list_items(ctx: Any, sid: UUID) -> list[Any]:  # noqa: ANN401
            return f.items[sid] if sid == ctx.user_id else []

        async def record(
            name: str, *a: Any, **k: Any
        ) -> dict[str, Any]:  # noqa: ANN401
            f.calls.append((name, a))
            return {"ok": name}

        def rec(name: str) -> Callable[..., Awaitable[dict[str, Any]]]:
            return lambda *a, **k: record(name, *a, **k)

        async def overview(
            ctx: Any, sid: UUID | None = None
        ) -> SimpleNamespace:  # noqa: ANN401
            return SimpleNamespace(entries=f.scores[ctx.user_id])

        async def listing(
            ctx: Any, sid: UUID | None = None
        ) -> list[Any]:  # noqa: ANN401
            return f.docs[ctx.user_id]

        async def download(
            ctx: Any, doc_id: UUID, version: Any = None
        ) -> Any:  # noqa: ANN401
            f.calls.append(("download", (doc_id,)))
            return SimpleNamespace(url=f"https://files/{doc_id}", expires_at=None)

        async def upload(
            ctx: Any, kind: str, name: str, data: bytes
        ) -> Any:  # noqa: ANN401
            f.calls.append(("upload", (kind, name)))
            return SimpleNamespace(doc=SimpleNamespace(id=new_id(), kind=kind))

        async def upload_limit(_user: UUID) -> int:
            return f.limit

        async def add_proof(ctx: Any, item_id: UUID, **kw: Any) -> Any:  # noqa: ANN401
            f.calls.append(("proof", (item_id, kw)))
            return SimpleNamespace(proof={"item_id": str(item_id)}, title=None)

        async def store_bytes(**kw: Any) -> Any:  # noqa: ANN401
            f.stored.append(kw)
            return SimpleNamespace(id=new_id())

        async def consent(ctx: Any) -> Any:  # noqa: ANN401
            return SimpleNamespace(grants=[], non_ai_mode=True, pending=[])

        async def search(filters: Any, **kw: Any) -> Any:  # noqa: ANN401
            return SimpleNamespace(items=[], next_cursor=None)

        async def sniff(_head: bytes) -> str:
            return f.sniffed

        admission = SimpleNamespace(
            actor=SimpleNamespace(execute=resolve),
            items=SimpleNamespace(
                list_items=list_items,
                create=rec("create_item"),
                update=rec("update_item"),
                delete=rec("delete_item"),
            ),
            proofs=SimpleNamespace(list=rec("list_proofs"), add=add_proof),
            test_scores=SimpleNamespace(
                overview=overview,
                create=rec("create_score"),
                update=rec("update_score"),
                delete=rec("delete_score"),
            ),
            documents=SimpleNamespace(
                listing=listing,
                download=download,
                upload=upload,
                upload_limit=upload_limit,
            ),
            privacy=SimpleNamespace(consent=consent),
            catalog=SimpleNamespace(search=search),
        )
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
            sniffer=SimpleNamespace(sniff=sniff),
            files=SimpleNamespace(store_bytes=store_bytes),
        )
        self.mcp = FastMCP("t")
        kit = ToolKit(
            self.mcp,
            cast(McpDeps, deps),
            ToolGuard(cast(McpDeps, deps), "admission"),
        )
        for module in (application, documents, catalog):
            module.register(kit)
        self.actor = Actor(ME, frozenset({Role.STUDENT}), scopes=SCOPES)

    def tool(self, name: str) -> Any:  # noqa: ANN401
        return self.mcp._tool_manager.get_tool(name)

    async def call(self, tool: str, /, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        fn = cast(Callable[..., Awaitable[dict[str, Any]]], self.tool(tool).fn)
        with patch.object(guard_module, "_token_actor", lambda: self.actor):
            return await fn(**kwargs)

    def mine(self) -> UUID:
        return cast(UUID, self.items[ME][0].item.id)

    def theirs(self) -> UUID:
        return cast(UUID, self.items[OTHER][0].item.id)


@pytest.fixture
def fx() -> Fixture:
    return Fixture()


async def test_another_students_activity_is_not_found_and_untouched(
    fx: Fixture,
) -> None:
    errors = []
    for item_id in (fx.theirs(), new_id()):
        for name, extra in (
            ("update_activity", {"lock_version": 0, "title": "x"}),
            ("delete_activity", {}),
            ("list_certificate_proofs", {}),
            ("add_certificate_proof", {"pasted_text": "cert"}),
        ):
            with pytest.raises(ToolError) as caught:
                await fx.call(name, item_id=item_id, **extra)
            errors.append((name, str(caught.value)))
    assert errors[:4] == errors[4:]
    assert fx.calls == []
    await fx.call("delete_activity", item_id=fx.mine())
    [(name, (_ctx, item_id))] = fx.calls
    assert (name, item_id) == ("delete_item", fx.mine())


async def test_another_students_test_score_is_not_found(fx: Fixture) -> None:
    theirs = fx.scores[OTHER][0].id
    with pytest.raises(ToolError):
        await fx.call("delete_test_score", entry_id=theirs)
    with pytest.raises(ToolError):
        await fx.call(
            "update_test_score", entry_id=theirs, test_id=new_id(), status="taken"
        )
    assert fx.calls == []
    await fx.call("delete_test_score", entry_id=fx.scores[ME][0].id)
    assert [c[0] for c in fx.calls] == ["delete_score"]


async def test_another_students_document_is_not_listed_or_read(fx: Fixture) -> None:
    listed = await fx.call("list_documents")
    assert [i["id"] for i in listed["items"]] == [str(fx.docs[ME][0].doc.id)]
    with pytest.raises(ToolError):
        await fx.call("read_document", document_id=fx.docs[OTHER][0].doc.id)
    assert fx.calls == []
    link = await fx.call("read_document", document_id=fx.docs[ME][0].doc.id)
    assert link["url"].endswith(str(fx.docs[ME][0].doc.id))


async def test_forged_scopes_on_a_staff_token_are_refused(fx: Fixture) -> None:
    fx.actor = Actor(COUNSELOR, frozenset({Role.COUNSELOR}), scopes=SCOPES)
    for name, args in (
        ("get_profile", {}),
        ("list_activities", {}),
        ("list_documents", {}),
        ("delete_activity", {"item_id": fx.mine()}),
        ("list_consents", {}),
    ):
        with pytest.raises(ToolError):
            await fx.call(name, **args)
    assert fx.calls == []
    assert (await fx.call("search_universities"))["items"] == []


async def test_a_student_token_without_the_scope_is_refused(fx: Fixture) -> None:
    fx.actor = Actor(ME, frozenset({Role.STUDENT}), scopes=frozenset({"catalog:read"}))
    for name in ("list_activities", "list_documents", "list_consents"):
        with pytest.raises(ToolError):
            await fx.call(name)


async def test_upload_is_sniffed_and_capped(fx: Fixture) -> None:
    content = base64.b64encode(PDF).decode()
    fx.sniffed = "text/html"
    with pytest.raises(ToolError):
        await fx.call(
            "upload_document", kind="passport", name="p.pdf", content_base64=content
        )
    fx.sniffed, fx.limit = "application/pdf", 8
    with pytest.raises(ToolError):
        await fx.call(
            "upload_document", kind="passport", name="p.pdf", content_base64=content
        )
    assert fx.calls == []
    fx.limit = 1024
    out = await fx.call(
        "upload_document", kind="passport", name="p.pdf", content_base64=content
    )
    assert out["kind"] == "passport"


async def test_a_proof_file_is_stored_as_the_callers_own(fx: Fixture) -> None:
    content = base64.b64encode(PDF).decode()
    await fx.call(
        "add_certificate_proof",
        item_id=fx.mine(),
        name="cert.pdf",
        content_base64=content,
    )
    [stored] = fx.stored
    assert stored["owner_id"] == ME
    assert stored["scope"] == FileScope.STUDENT
    assert stored["purpose"] == FilePurpose.ADMISSION_DOCUMENT
    [(name, (item_id, kw))] = fx.calls
    assert name == "proof" and item_id == fx.mine() and kw["file_id"] is not None
    with pytest.raises(ToolError):
        await fx.call(
            "add_certificate_proof", item_id=fx.mine(), url="https://a", pasted_text="b"
        )


def test_delete_tools_are_flagged_destructive(fx: Fixture) -> None:
    for name in ("delete_activity", "delete_test_score"):
        assert fx.tool(name).annotations.destructiveHint is True
    for name in ("add_activity", "upload_document", "add_certificate_proof"):
        assert fx.tool(name).annotations.destructiveHint is False
