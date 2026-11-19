"""Exemplar library: validation, import, token limits, student excerpts."""

from typing import Any

from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.exemplars import (
    ExemplarInput,
    ExemplarService,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ExemplarDuplicateError,
    ExemplarInvalidError,
)
from app.modules.admission.domain.exemplars import excerpt
from app.shared.actor import Actor, Role
from tests.admission.unit.fakes import NOW, FakeMembership
from tests.admission.unit.fakes_exemplars import FakeExemplarStore, FakeExemplarUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, _assign
from tests.fakes.clock import FixedClock

import pytest

URL = "https://example.com/essay"


class World:
    def __init__(self) -> None:
        self.store = FakeExemplarStore()
        self.svc = ExemplarService(lambda: FakeExemplarUow(self.store), FixedClock(NOW))
        self.resolver = ResolveAdmissionActor(
            lambda: FakeExemplarUow(self.store),
            FakeMembership(),
            FixedClock(NOW),
            {10, 11},
        )

    async def counselor(self, *, token: bool = False) -> AdmissionContext:
        self.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
        scopes = frozenset({"admission:catalog"}) if token else frozenset()
        actor = Actor(STAFF, frozenset({Role.COUNSELOR}), scopes=scopes)
        return await self.resolver.execute(actor)

    async def student(self) -> AdmissionContext:
        return await self.resolver.execute(Actor(STUDENT, frozenset({Role.STUDENT})))


def data(**kw: Any) -> ExemplarInput:
    base: dict[str, Any] = {
        "kind": "personal_statement",
        "title": "My essay",
        "body": "word " * 100,
        "source_url": URL,
    }
    return ExemplarInput(**{**base, **kw})


async def invalid(coro: Any, field: str) -> None:
    with pytest.raises(ExemplarInvalidError) as caught:
        await coro
    assert caught.value.params["field"] == field


@pytest.mark.parametrize(("n", "ok"), [(200, True), (201, False)])
async def test_title_limit(n: int, ok: bool) -> None:
    """ADM-EXM-1: a title of 200 characters is stored, 201 is refused."""
    w = World()
    ctx = await w.counselor()
    if ok:
        await w.svc.create(ctx, data(title="t" * n))
    else:
        await invalid(w.svc.create(ctx, data(title="t" * n)), "title")


@pytest.mark.parametrize(("n", "ok"), [(20000, True), (20001, False)])
async def test_body_limit(n: int, ok: bool) -> None:
    """ADM-EXM-1: a body of 20000 characters is stored, 20001 is refused."""
    w = World()
    ctx = await w.counselor()
    if ok:
        await w.svc.create(ctx, data(body="b" * n))
    else:
        await invalid(w.svc.create(ctx, data(body="b" * n)), "body")


@pytest.mark.parametrize(("n", "ok"), [(12, True), (13, False)])
async def test_tag_count_limit(n: int, ok: bool) -> None:
    """ADM-EXM-1: 12 tags are stored, 13 are refused."""
    w = World()
    ctx = await w.counselor()
    tags = [f"t{i}" for i in range(n)]
    if ok:
        await w.svc.create(ctx, data(tags=tags))
    else:
        await invalid(w.svc.create(ctx, data(tags=tags)), "tags")


@pytest.mark.parametrize(("n", "ok"), [(40, True), (41, False)])
async def test_tag_length_limit(n: int, ok: bool) -> None:
    """ADM-EXM-1: a tag of 40 characters is stored, 41 is refused."""
    w = World()
    ctx = await w.counselor()
    if ok:
        await w.svc.create(ctx, data(tags=["a" * n]))
    else:
        await invalid(w.svc.create(ctx, data(tags=["a" * n])), "tags")


async def test_plain_http_source_is_refused() -> None:
    """ADM-EXM-2: a source link must be https."""
    w = World()
    ctx = await w.counselor()
    await invalid(w.svc.create(ctx, data(source_url="http://x.com/a")), "source_url")


async def test_excerpt_is_exactly_eighty_words() -> None:
    """ADM-EXM-3: the excerpt keeps 80 words and a shorter body whole."""
    assert len(excerpt("w " * 200).split()) == 80
    assert excerpt("one two three") == "one two three"


async def test_import_limit_and_duplicates() -> None:
    """ADM-EXM-4: 50 items import, 51 are refused, a known one is a duplicate."""
    w = World()
    ctx = await w.counselor()
    items = [data(title=f"t{i}") for i in range(50)]
    res = await w.svc.import_many(ctx, items)
    assert len(res.created) == 50 and not res.duplicates
    again = await w.svc.import_many(ctx, items[:2] + [data(title="new")])
    assert len(again.created) == 1 and len(again.duplicates) == 2
    await invalid(
        w.svc.import_many(ctx, [data(title=f"x{i}") for i in range(51)]), "items"
    )
    with pytest.raises(ExemplarDuplicateError):
        await w.svc.create(ctx, data(title="t0"))


async def test_token_creates_drafts_only() -> None:
    """ADM-EXM-5: a catalog token cannot publish, edit or delete."""
    w = World()
    ctx = await w.counselor(token=True)
    item = await w.svc.create(ctx, data(status="published"))
    assert item.status == "draft"
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.update(ctx, item.id, {"title": "x"}, lock_version=0)
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.delete(ctx, item.id)


async def test_without_permission_is_forbidden() -> None:
    """ADM-EXM-6: a caller without exemplars:curate is refused."""
    w = World()
    ctx = await w.student()
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.create(ctx, data())


async def test_publish_and_student_sees_excerpt_only() -> None:
    """ADM-EXM-7: a student gets 404 for a draft and no body for a published one."""
    w = World()
    cns = await w.counselor()
    stu = await w.student()
    item = await w.svc.create(cns, data())
    with pytest.raises(AdmissionNotFoundError):
        await w.svc.get_public(stu, item.id)
    pub = await w.svc.update(cns, item.id, {"status": "published"}, lock_version=0)
    view = await w.svc.get_public(stu, pub.id)
    assert not hasattr(view, "body") and len(view.excerpt.split()) <= 80
    page = await w.svc.list_public(
        stu, kind=None, institution_id=None, query=None, limit=10, offset=0
    )
    assert page.total == 1
    assert any(e.action == "exemplar.published" for e in w.store.audit)


async def test_stale_lock_conflicts() -> None:
    """ADM-EXM-8: an edit on a stale lock version is a conflict."""
    from app.modules.admission.domain.errors import AdmissionConflictError

    w = World()
    ctx = await w.counselor()
    item = await w.svc.create(ctx, data())
    await w.svc.update(ctx, item.id, {"title": "a"}, lock_version=0)
    with pytest.raises(AdmissionConflictError):
        await w.svc.update(ctx, item.id, {"title": "b"}, lock_version=0)
