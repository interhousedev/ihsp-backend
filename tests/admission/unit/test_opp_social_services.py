"""Comment and organization services over in-memory repositories."""

import dataclasses
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.opportunity_comments import (
    OppCommentService,
)
from app.modules.admission.application.orgs import OrgService
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    InvalidTransitionError,
)
from app.modules.admission.domain.opportunity_comments import (
    OppComment,
    OppCommentReport,
)
from app.modules.admission.domain.orgs import Organization
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW
from tests.fakes.clock import FixedClock

import pytest

ADMIN = new_id()
AUTHOR = new_id()
OTHER = new_id()


class _Comments:
    def __init__(self) -> None:
        self.rows: dict[UUID, OppComment] = {}
        self.reports: dict[UUID, OppCommentReport] = {}

    async def add(self, c: OppComment) -> OppComment:
        self.rows[c.id] = c
        return c

    async def get(self, cid: UUID) -> OppComment | None:
        return self.rows.get(cid)

    async def save(self, c: OppComment) -> OppComment:
        self.rows[c.id] = c
        return c

    async def add_report(self, r: OppCommentReport) -> bool:
        if any(
            x.comment_id == r.comment_id and x.reporter_id == r.reporter_id
            for x in self.reports.values()
        ):
            return False
        self.reports[r.id] = r
        return True

    async def get_report(self, rid: UUID) -> OppCommentReport | None:
        return self.reports.get(rid)

    async def save_report(self, r: OppCommentReport) -> OppCommentReport:
        self.reports[r.id] = r
        return r

    async def open_reports(self) -> list[OppCommentReport]:
        return [r for r in self.reports.values() if r.status == "open"]

    async def reports_of(self, cid: UUID) -> list[OppCommentReport]:
        return [r for r in await self.open_reports() if r.comment_id == cid]


class _Orgs:
    def __init__(self) -> None:
        self.rows: dict[UUID, Organization] = {}

    async def get(self, oid: UUID) -> Organization | None:
        return self.rows.get(oid)

    async def save(self, o: Organization) -> Organization:
        self.rows[o.id] = o
        return o

    async def delete(self, oid: UUID) -> None:
        self.rows.pop(oid, None)


class _Opps:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def list_published(self) -> list[Any]:
        return self.published


class _Uow:
    def __init__(self) -> None:
        self.opp_comments = _Comments()
        self.orgs = _Orgs()
        self.opportunities = _Opps()
        self.sent: list[Any] = []

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    def notify(self, draft: Any) -> None:
        self.sent.append(draft)


class _Identity:
    async def get_users(self, ids: Any) -> dict[UUID, Any]:
        return {}

    async def user_ids_with_roles(self, roles: Any) -> list[UUID]:
        assert list(roles) == [Role.ADMIN]
        return [ADMIN]


class _Opportunities:
    def can_moderate(self, ctx: Any) -> bool:
        return ctx.user_id == ADMIN


def _ctx(user_id: UUID) -> Any:
    return SimpleNamespace(user_id=user_id, admission=SimpleNamespace())


def _world() -> tuple[_Uow, OppCommentService, OrgService]:
    uow = _Uow()
    clock = FixedClock(NOW)
    comments = OppCommentService(
        lambda: uow, _Opportunities(), clock, _Identity()  # type: ignore[arg-type]
    )
    orgs = OrgService(lambda: uow, _Opportunities(), clock)  # type: ignore[arg-type]
    return uow, comments, orgs


async def _seed(uow: _Uow, **kw: object) -> OppComment:
    c = OppComment(
        id=new_id(),
        opportunity_id=new_id(),
        author_id=AUTHOR,
        body="hi",
        created_at=NOW,
    )
    c = dataclasses.replace(c, **kw)  # type: ignore[arg-type]
    return await uow.opp_comments.add(c)


async def test_author_deletes_own_comment_only() -> None:
    uow, svc, _ = _world()
    c = await _seed(uow)
    with pytest.raises(AdmissionForbiddenError):
        await svc.delete(_ctx(OTHER), c.id)
    await svc.delete(_ctx(AUTHOR), c.id)
    assert uow.opp_comments.rows[c.id].status == "deleted"


async def test_hide_needs_moderator_and_resolves_reports() -> None:
    uow, svc, _ = _world()
    c = await _seed(uow)
    await svc.report(_ctx(OTHER), c.id, "spam")
    with pytest.raises(AdmissionForbiddenError):
        await svc.hide(_ctx(OTHER), c.id)
    await svc.hide(_ctx(ADMIN), c.id)
    assert uow.opp_comments.rows[c.id].status == "hidden"
    assert [r.status for r in uow.opp_comments.reports.values()] == ["resolved"]
    await svc.unhide(_ctx(ADMIN), c.id)
    assert uow.opp_comments.rows[c.id].status == "published"
    with pytest.raises(AdmissionForbiddenError):
        await svc.unhide(_ctx(OTHER), c.id)


async def test_report_queues_notifies_admins_once() -> None:
    uow, svc, _ = _world()
    c = await _seed(uow)
    await svc.report(_ctx(OTHER), c.id, "spam")
    await svc.report(_ctx(OTHER), c.id, "spam again")
    assert len(uow.opp_comments.reports) == 1
    assert len(uow.sent) == 1
    assert uow.sent[0].user_id == ADMIN
    assert uow.sent[0].payload["kind"] == "opportunity_report"
    queue = await svc.reports(_ctx(ADMIN))
    assert [v.comment.id for v in queue] == [c.id]
    with pytest.raises(AdmissionForbiddenError):
        await svc.reports(_ctx(OTHER))


async def test_report_rejects_own_and_hidden_comments() -> None:
    uow, svc, _ = _world()
    c = await _seed(uow)
    with pytest.raises(InvalidTransitionError):
        await svc.report(_ctx(AUTHOR), c.id, "mine")
    h = await _seed(uow, status="hidden")
    with pytest.raises(InvalidTransitionError):
        await svc.report(_ctx(OTHER), h.id, "x")


async def test_dismiss_closes_report_and_keeps_comment() -> None:
    uow, svc, _ = _world()
    c = await _seed(uow)
    await svc.report(_ctx(OTHER), c.id, "spam")
    (rid,) = uow.opp_comments.reports
    await svc.dismiss(_ctx(ADMIN), rid)
    assert uow.opp_comments.reports[rid].status == "dismissed"
    assert uow.opp_comments.rows[c.id].status == "published"
    assert await svc.reports(_ctx(ADMIN)) == []


async def test_org_delete_conflicts_while_in_use() -> None:
    uow, _, orgs = _world()
    org = await orgs.create(_ctx(ADMIN), name="Fulbright", kind="foundation")
    uow.opportunities.published = [
        SimpleNamespace(draft=SimpleNamespace(org_id=org.id))
    ]
    with pytest.raises(AdmissionConflictError):
        await orgs.delete(_ctx(ADMIN), org.id)
    uow.opportunities.published = []
    await orgs.delete(_ctx(ADMIN), org.id)
    assert org.id not in uow.orgs.rows
    with pytest.raises(AdmissionForbiddenError):
        await orgs.create(_ctx(OTHER), name="X", kind="foundation")
