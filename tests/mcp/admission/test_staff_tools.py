"""Staff tools of the admission server: scope, caseload, consent, documents, essays."""

from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

from app.interfaces.mcp import guard as guard_module
from app.interfaces.mcp.admission.tools.staff import register_staff
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.guard import ToolGuard
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.application.access import VIEWED
from app.modules.admission.application.staff import CaseloadItem
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.staff import CaseloadRow
from app.modules.admission.ports.consent import AI, STAFF_VIEW
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import FakeConsents
from tests.admission.unit.test_access_policy import (
    OTHER,
    STAFF,
    STUDENT,
    World,
    _assign,
)

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

SCOPES = frozenset(
    {"caseload:read", "students:read", "students:write", "documents:review"}
)
DOC_PASSPORT, DOC_REC, DOC_BANK, DOC_SCHOOL = (new_id() for _ in range(4))


def _doc(doc_id: UUID, kind: str, visibility: str = "student") -> SimpleNamespace:
    doc = SimpleNamespace(
        id=doc_id,
        student_id=STUDENT,
        kind=kind,
        visibility=visibility,
        review_status="none",
        current_version=1,
        created_at=None,
        reject_reason_code=None,
    )
    return SimpleNamespace(doc=doc, can_download=True)


DOCS = [
    _doc(DOC_PASSPORT, "passport"),
    _doc(DOC_REC, "rec", "confidential"),
    _doc(DOC_BANK, "bank"),
    _doc(DOC_SCHOOL, "school_report", "confidential"),
]
ESSAY_VERSIONS = [
    SimpleNamespace(version=1, body="private draft", shared=False),
    SimpleNamespace(version=2, body="shared draft", shared=True),
]


class Fixture:
    def __init__(self, *, ai: bool = True) -> None:  # noqa: C901 - fake closures
        self.w = World()
        self.w.store.assignments[STAFF] = (
            _assign("counselor_full", "student", STUDENT),
        )
        grants = {STUDENT: frozenset({STAFF_VIEW} | ({AI} if ai else set()))}
        self.consents = FakeConsents(grants)
        self.reviewed: list[UUID] = []
        policy = self.w.policy
        w = self.w

        async def caseload(
            ctx: Any, filters: Any
        ) -> list[CaseloadItem]:  # noqa: ANN401
            ids = await policy.students_in_scope(ctx) or []
            return [
                CaseloadItem(
                    CaseloadRow(i, "drafting", None, 0, 0, "11-A"),
                    None,
                    False,
                    "Ann Student",
                )
                for i in ids
            ]

        async def profile(ctx: Any, sid: UUID) -> dict[str, Any]:  # noqa: ANN401
            await policy.require(ctx, sid, Permission.PROFILE_READ)
            return {"answers": {"goal": "CS"}}

        async def essays(ctx: Any, sid: UUID) -> list[dict[str, Any]]:  # noqa: ANN401
            await policy.require(ctx, sid, Permission.ESSAYS_READ)
            return [{"versions": [v.body for v in ESSAY_VERSIONS if v.shared]}]

        async def listing(ctx: Any, sid: UUID) -> list[SimpleNamespace]:  # noqa: ANN401
            await policy.require(ctx, sid, Permission.DOCUMENTS_READ)
            return DOCS

        async def download(
            ctx: Any, doc_id: UUID, version: Any = None
        ) -> Any:  # noqa: ANN401
            return SimpleNamespace(url=f"https://files/{doc_id}", expires_at=None)

        async def review(
            ctx: Any, doc_id: UUID, **kw: Any
        ) -> SimpleNamespace:  # noqa: ANN401
            self.reviewed.append(doc_id)
            return next(d for d in DOCS if d.doc.id == doc_id)

        async def queue(
            ctx: Any, status: Any = None
        ) -> list[SimpleNamespace]:  # noqa: ANN401
            return DOCS

        async def empty(*a: Any, **k: Any) -> list[Any]:  # noqa: ANN401
            return []

        self.admission = SimpleNamespace(
            actor=w.resolver,
            access=policy,
            consents=self.consents,
            staff=SimpleNamespace(caseload=caseload),
            profile=SimpleNamespace(get=profile),
            items=SimpleNamespace(list_items=empty),
            test_scores=SimpleNamespace(overview=empty),
            essays=SimpleNamespace(list_shared=essays),
            tasks=SimpleNamespace(list_for=empty),
            documents=SimpleNamespace(
                listing=listing, download=download, review=review, staff_queue=queue
            ),
        )
        limiter = SimpleNamespace(hit=_noop)
        deps = SimpleNamespace(
            t=lambda key, **p: key,
            maintenance=None,
            rate_limiter=limiter,
            consent=None,
            scope_overlay=None,
            limits=SimpleNamespace(
                ai_access=lambda _u: _ready(SimpleNamespace(blocks=lambda _s: False))
            ),
            audit=SimpleNamespace(audit=_noop),
            call_log=SimpleNamespace(record=_noop),
            admission=self.admission,
        )
        mcp = FastMCP("t")
        guard = ToolGuard(cast(McpDeps, deps), "admission")
        register_staff(ToolKit(mcp, cast(McpDeps, deps), guard))
        self.mcp = mcp
        self.actor = Actor(STAFF, frozenset({Role.COUNSELOR}), scopes=SCOPES)

    async def call(self, name: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        fn = cast(
            Callable[..., Awaitable[dict[str, Any]]],
            self.mcp._tool_manager.get_tool(name).fn,  # type: ignore[union-attr]
        )
        with patch.object(guard_module, "_token_actor", lambda: self.actor):
            return await fn(**kwargs)


async def _noop(*a: Any, **k: Any) -> None:  # noqa: ANN401
    return None


async def _ready(value: Any) -> Any:  # noqa: ANN401
    return value


@pytest.fixture
async def fx() -> AsyncIterator[Fixture]:
    yield Fixture()


async def test_counselor_reads_an_assigned_student_and_it_is_audited(
    fx: Fixture,
) -> None:
    out = await fx.call("get_student_application", student_id=STUDENT)
    assert out["profile"] == {"answers": {"goal": "CS"}}
    assert "withheld" not in out
    assert any(e.action == VIEWED and e.student_id == STUDENT for e in fx.w.store.audit)


async def test_unassigned_and_random_students_give_the_same_not_found(
    fx: Fixture,
) -> None:
    errors = []
    for sid in (OTHER, new_id()):
        with pytest.raises(ToolError) as caught:
            await fx.call("get_student_application", student_id=sid)
        errors.append(str(caught.value))
    assert errors[0] == errors[1]
    with pytest.raises(ToolError):
        await fx.call("list_student_documents", student_id=OTHER)


async def test_a_student_token_with_a_forged_staff_scope_is_refused(
    fx: Fixture,
) -> None:
    fx.actor = Actor(STUDENT, frozenset({Role.STUDENT}), scopes=SCOPES)
    for name, args in (
        ("list_caseload", {}),
        ("get_student_application", {"student_id": STUDENT}),
        ("list_student_documents", {"student_id": STUDENT}),
    ):
        with pytest.raises(ToolError):
            await fx.call(name, **args)


async def test_a_staff_token_without_the_scope_is_refused(fx: Fixture) -> None:
    fx.actor = Actor(STAFF, frozenset({Role.COUNSELOR}), scopes=frozenset())
    with pytest.raises(ToolError):
        await fx.call("list_caseload")


async def test_rec_and_bank_documents_are_never_listed_or_read(fx: Fixture) -> None:
    listed = await fx.call("list_student_documents", student_id=STUDENT)
    assert [i["document_id"] for i in listed["items"]] == [str(DOC_PASSPORT)]
    queue = await fx.call("list_document_queue")
    assert [i["document_id"] for i in queue["items"]] == [str(DOC_PASSPORT)]
    for doc_id in (DOC_REC, DOC_BANK, DOC_SCHOOL):
        with pytest.raises(ToolError):
            await fx.call(
                "read_student_document", student_id=STUDENT, document_id=doc_id
            )
        with pytest.raises(ToolError):
            await fx.call(
                "review_document",
                student_id=STUDENT,
                document_id=doc_id,
                accept=True,
            )
    assert fx.reviewed == []
    link = await fx.call(
        "read_student_document", student_id=STUDENT, document_id=DOC_PASSPORT
    )
    assert link["url"].endswith(str(DOC_PASSPORT))
    await fx.call(
        "review_document", student_id=STUDENT, document_id=DOC_PASSPORT, accept=True
    )
    assert fx.reviewed == [DOC_PASSPORT]


async def test_a_student_without_ai_consent_is_withheld() -> None:
    fx = Fixture(ai=False)
    out = await fx.call("get_student_application", student_id=STUDENT)
    assert out == {
        "student_id": str(STUDENT),
        "name": "Ann Student",
        "withheld": "ai-consent",
    }
    docs = await fx.call("list_student_documents", student_id=STUDENT)
    assert docs["withheld"] == "ai-consent" and "items" not in docs
    caseload = await fx.call("list_caseload")
    [row] = caseload["items"]
    assert row["withheld"] == "ai-consent" and "stage" not in row
    queue = await fx.call("list_document_queue")
    assert queue["items"] == [] and queue["withheld"]
    with pytest.raises(ToolError):
        await fx.call("get_student_application", student_id=new_id())
    with pytest.raises(AdmissionNotFoundError):
        await fx.w.policy.require(
            await fx.w.ctx(STAFF, Role.COUNSELOR), OTHER, Permission.PROFILE_READ
        )


async def test_essays_appear_only_as_shared_versions(fx: Fixture) -> None:
    out = await fx.call(
        "get_student_application", student_id=STUDENT, sections=["essays"]
    )
    assert out["essays"] == [{"versions": ["shared draft"]}]
    assert "private draft" not in str(out)


async def test_caseload_lists_only_assigned_students(fx: Fixture) -> None:
    out = await fx.call("list_caseload")
    assert [r["student_id"] for r in out["items"]] == [str(STUDENT)]
    assert out["items"][0]["stage"] == "drafting"


async def test_profile_never_carries_the_budget_or_finance_answers(
    fx: Fixture,
) -> None:
    async def profile(ctx: Any, sid: UUID) -> dict[str, Any]:  # noqa: ANN401
        return {
            "family_budget": "over_50k",
            "budget_shared": True,
            "answers": {"q32": "over_50k", "q33": "full", "q34": ["merit"], "q1": "A"},
        }

    fx.admission.profile.get = profile
    out = await fx.call(
        "get_student_application", student_id=STUDENT, sections=["profile"]
    )
    assert out["profile"] == {"answers": {"q1": "A"}}


async def test_student_authored_text_is_cleaned_and_marked(fx: Fixture) -> None:
    async def tasks(ctx: Any, sid: UUID) -> list[dict[str, Any]]:  # noqa: ANN401
        return [{"title": "do\u202eit\x00"}]

    async def thread(*a: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        return [{"body": "hi\u200b"}]

    fx.admission.tasks.list_for = tasks
    fx.admission.comments = SimpleNamespace(thread=thread)
    out = await fx.call("get_student_application", student_id=STUDENT)
    assert out["tasks"] == [{"title": "doit"}]
    assert out["untrusted_fields"] == ["profile", "activities", "essays", "tasks"]
    comments = await fx.call(
        "list_comments", student_id=STUDENT, target_kind="profile", target_id=STUDENT
    )
    assert comments == {"items": [{"body": "hi"}], "untrusted_fields": ["items"]}


async def test_filters_never_reveal_state_of_withheld_students() -> None:
    fx = Fixture(ai=False)
    for args in ({"stage": "drafting"}, {"at_risk": True}):
        out = await fx.call("list_caseload", **args)
        assert out == {"items": [], "total": 0, "offset": 0}
    queue = await fx.call("list_document_queue", review_status="none")
    assert queue == {"items": [], "withheld": []}
