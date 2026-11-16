"""Test scores: authz, catalog rules, verification, calendar source."""

import dataclasses
import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.application.calendar import ScoreCalendarSource
from app.modules.admission.application.test_scores import ScoreService
from app.modules.admission.domain.documents import DocumentRecord
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ItemLimitError,
    ScoreInvalidError,
)
from app.modules.admission.domain.test_scores import (
    MAX_ENTRIES,
    ScoreEntry,
    ScoreEntryDraft,
    ScoreTest,
)
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.score_defs import SAT, make_test
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World, _assign
from tests.fakes.clock import FixedClock

import pytest


class FakeScoreRepo:
    """In-memory ScoreRepository."""

    def __init__(self) -> None:
        self.tests: dict[UUID, ScoreTest] = {}
        self.rows: dict[UUID, ScoreEntry] = {}

    async def catalog(self, include_inactive: bool = False) -> list[ScoreTest]:
        return [t for t in self.tests.values() if include_inactive or t.active]

    async def get_test(self, test_id: UUID) -> ScoreTest | None:
        return self.tests.get(test_id)

    async def key_taken(self, key: str, except_id: UUID | None = None) -> bool:
        return any(t.key == key and t.id != except_id for t in self.tests.values())

    async def save_test(self, test: ScoreTest) -> ScoreTest:
        self.tests[test.id] = test
        return test

    async def delete_test(self, test_id: UUID) -> None:
        self.tests.pop(test_id, None)

    async def test_in_use(self, test_id: UUID) -> bool:
        return any(e.test_id == test_id for e in self.rows.values())

    async def entries(self, student_id: UUID) -> list[ScoreEntry]:
        return [e for e in self.rows.values() if e.student_id == student_id]

    async def get_entry(self, entry_id: UUID) -> ScoreEntry | None:
        return self.rows.get(entry_id)

    async def save_entry(self, entry: ScoreEntry) -> ScoreEntry:
        self.rows[entry.id] = entry
        return entry

    async def delete_entry(self, entry_id: UUID) -> None:
        self.rows.pop(entry_id, None)


class FakeDocs:
    """Documents by id."""

    def __init__(self) -> None:
        self.rows: dict[UUID, DocumentRecord] = {}

    async def get(self, document_id: UUID) -> DocumentRecord | None:
        return self.rows.get(document_id)


class Env:
    def __init__(self, consent: bool = True) -> None:
        self.w = World(consent=consent)
        self.repo = FakeScoreRepo()
        self.docs = FakeDocs()
        self.repo.tests[SAT.id] = SAT

        def uow() -> FakeUow:
            u = FakeUow(self.w.store)
            u.test_scores = self.repo  # type: ignore[attr-defined]
            u.documents = self.docs  # type: ignore[attr-defined]
            return u

        self.svc = ScoreService(uow, self.w.policy, FixedClock(NOW))  # type: ignore

    async def student(self) -> Any:
        return await self.w.ctx(STUDENT, Role.STUDENT)

    async def admin(self) -> Any:
        return await self.w.ctx(STAFF, Role.ADMIN)

    async def counselor(self) -> Any:
        self.w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
        return await self.w.ctx(STAFF, Role.COUNSELOR)


def draft(**kw: Any) -> ScoreEntryDraft:
    base: dict[str, Any] = {
        "test_id": SAT.id,
        "status": "score_received",
        "sections": {"ebrw": 700, "math": 750},
    }
    base.update(kw)
    return ScoreEntryDraft(**base)


@pytest.mark.asyncio
async def test_create_computes_total_and_summary() -> None:
    e = Env()
    ctx = await e.student()
    saved = await e.svc.create(ctx, draft())
    assert saved.total == 1450
    await e.svc.create(
        ctx, draft(sections={"ebrw": 760, "math": 700}, test_date=dt.date(2026, 1, 1))
    )
    ov = await e.svc.overview(ctx)
    assert ov.is_owner and not ov.can_verify
    (s,) = ov.summaries
    assert s.superscore_total == 1510


@pytest.mark.asyncio
async def test_out_of_range_rejected() -> None:
    e = Env()
    with pytest.raises(ScoreInvalidError):
        await e.svc.create(await e.student(), draft(sections={"ebrw": 900, "math": 1}))


@pytest.mark.asyncio
async def test_staff_cannot_write_and_foreign_entry_is_404() -> None:
    e = Env()
    saved = await e.svc.create(await e.student(), draft())
    staff = await e.counselor()
    with pytest.raises((AdmissionForbiddenError, AdmissionNotFoundError)):
        await e.svc.create(staff, draft())
    with pytest.raises(AdmissionNotFoundError):
        await e.svc.update(await e.w.ctx(STAFF, Role.STUDENT), saved.id, draft())


@pytest.mark.asyncio
async def test_staff_views_and_verifies() -> None:
    e = Env()
    saved = await e.svc.create(await e.student(), draft())
    staff = await e.counselor()
    ov = await e.svc.overview(staff, STUDENT)
    assert ov.can_verify and not ov.is_owner and len(ov.entries) == 1
    done = await e.svc.verify(staff, saved.id, True)
    assert done.verified_by == STAFF
    again = await e.svc.update(await e.student(), saved.id, draft())
    assert again.verified_by is None and again.verified_at is None


@pytest.mark.asyncio
async def test_owner_cannot_verify() -> None:
    e = Env()
    ctx = await e.student()
    saved = await e.svc.create(ctx, draft())
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.verify(ctx, saved.id, True)


@pytest.mark.asyncio
async def test_verify_needs_received_score() -> None:
    e = Env()
    saved = await e.svc.create(
        await e.student(),
        ScoreEntryDraft(test_id=SAT.id, status="planned"),
    )
    with pytest.raises(AdmissionConflictError):
        await e.svc.verify(await e.counselor(), saved.id, True)


@pytest.mark.asyncio
async def test_no_consent_blocks_staff_view() -> None:
    e = Env(consent=False)
    await e.svc.create(await e.student(), draft())
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.overview(await e.counselor(), STUDENT)


@pytest.mark.asyncio
async def test_foreign_certificate_rejected() -> None:
    e = Env()
    doc = DocumentRecord(
        new_id(), STAFF, "test_report", "private", STAFF  # type: ignore
    )
    e.docs.rows[doc.id] = doc
    with pytest.raises(ScoreInvalidError):
        await e.svc.create(await e.student(), draft(certificate_document_id=doc.id))
    mine = dataclasses.replace(doc, id=new_id(), student_id=STUDENT)
    e.docs.rows[mine.id] = mine
    ok = await e.svc.create(await e.student(), draft(certificate_document_id=mine.id))
    assert ok.certificate_document_id == mine.id


@pytest.mark.asyncio
async def test_catalog_admin_only_and_rules() -> None:
    e = Env()
    new = make_test("extra_test", (), None, "none")
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.save_test(await e.student(), None, new)
    admin = await e.admin()
    dup = dataclasses.replace(new, key="sat")
    with pytest.raises(AdmissionConflictError):
        await e.svc.save_test(admin, None, dup)
    await e.svc.create(await e.student(), draft())
    with pytest.raises(AdmissionConflictError):
        await e.svc.delete_test(admin, SAT.id)
    saved = await e.svc.save_test(admin, None, new)
    await e.svc.delete_test(admin, saved.id)
    inactive = dataclasses.replace(SAT, active=False)
    await e.svc.save_test(admin, SAT.id, inactive)
    assert await e.svc.catalog(await e.student()) == []
    assert len(await e.svc.catalog(admin)) == 1


@pytest.mark.asyncio
async def test_entry_limit() -> None:
    e = Env()
    ctx = await e.student()
    for _ in range(MAX_ENTRIES):
        await e.svc.create(ctx, ScoreEntryDraft(test_id=SAT.id, status="planned"))
    with pytest.raises(ItemLimitError):
        await e.svc.create(ctx, ScoreEntryDraft(test_id=SAT.id, status="planned"))


@pytest.mark.asyncio
async def test_calendar_source_entries() -> None:
    e = Env()
    ctx = await e.student()
    planned = await e.svc.create(
        ctx,
        ScoreEntryDraft(
            test_id=SAT.id,
            status="planned",
            test_date=dt.date(2026, 5, 2),
            registration_deadline=dt.date(2026, 4, 17),
        ),
    )
    await e.svc.create(
        ctx, draft(test_date=dt.date(2026, 5, 3))
    )  # taken: not on the calendar
    src = ScoreCalendarSource(
        e.svc.dated, e.w.store, lambda loc, key, **kw: key  # type: ignore[arg-type]
    )
    out = await src.entries(STUDENT, dt.date(2026, 4, 1), dt.date(2026, 6, 1), "en")
    assert {x.key for x in out} == {
        f"tscore:{planned.id}:registration",
        f"tscore:{planned.id}:day",
    }
    assert all(x.source == "test_score" and x.remind for x in out)


@pytest.mark.asyncio
async def test_entry_of_a_deactivated_test_stays_editable() -> None:
    e = Env()
    ctx = await e.student()
    saved = await e.svc.create(ctx, draft())
    await e.svc.save_test(
        await e.admin(), SAT.id, dataclasses.replace(SAT, active=False)
    )
    updated = await e.svc.update(
        ctx, saved.id, draft(sections={"ebrw": 600, "math": 600})
    )
    assert updated.total == 1200
    with pytest.raises(ScoreInvalidError):
        await e.svc.create(ctx, draft())


@pytest.mark.asyncio
async def test_counselor_edits_catalog_mentor_refused() -> None:
    e = Env()
    new = make_test("extra_test", (), None, "none")
    saved = await e.svc.save_test(await e.counselor(), None, new)
    await e.svc.delete_test(await e.counselor(), saved.id)
    e.w.store.assignments[STAFF] = (_assign("student_counselor", "all", None),)
    mentor = await e.w.ctx(STAFF, Role.MENTOR)
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.save_test(mentor, None, new)
