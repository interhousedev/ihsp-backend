"""Types and entries: the same suite runs on the in-memory fake and on PostgreSQL."""

from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.entry import (
    CertificateEntry,
    EntryFile,
    EntrySource,
)
from app.modules.certificates.infrastructure.uow import SqlCertificatesUnitOfWork
from app.modules.certificates.ports.entry_repository import EntryFilter
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.fakes.certificates.uow import FakeCertificatesStore, fake_uow_factory

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.fixture(params=["fake", "sql"])
def uow_factory(request: pytest.FixtureRequest) -> UowFactory:
    """The unit of work under test: in memory, or SQL on the test transaction."""
    if request.param == "fake":
        return fake_uow_factory(FakeCertificatesStore())
    sessionmaker: async_sessionmaker[AsyncSession] = request.getfixturevalue(
        "sessionmaker_in_tx"
    )
    return lambda: SqlCertificatesUnitOfWork(
        sessionmaker, noop_outbox_writer, noop_audit_writer
    )


def make_type(code: str, **fields: object) -> CertificateType:
    """A type entity."""
    values: dict[str, object] = {
        "id": new_id(),
        "code": code,
        "name": {"uz": code, "ru": code, "en": code},
    }
    values.update(fields)
    return CertificateType(**values)  # type: ignore[arg-type]


def make_entry(student: UUID, type_id: UUID, **fields: object) -> CertificateEntry:
    """An entry entity."""
    values: dict[str, object] = {
        "id": new_id(),
        "student_id": student,
        "type_id": type_id,
        "created_at": NOW,
    }
    values.update(fields)
    return CertificateEntry(**values)  # type: ignore[arg-type]


async def test_types_round_trip_in_position_order(uow_factory: UowFactory) -> None:
    """Json fields survive; the list is ordered by position; codes are found."""
    second = make_type("sat", position=1, score_min=400.0, score_max=1600.0)
    first = make_type(
        "ielts", position=0, levels=["6.5", "7.0"], asks_level=True, builtin=True
    )
    async with uow_factory() as uow:
        await uow.types.add(second)
        await uow.types.add(first)
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.types.list_all()
        by_code = await uow.types.get_by_code("sat")
        next_position = await uow.types.next_position()

    assert [t.code for t in listed] == ["ielts", "sat"]
    assert listed[0].levels == ["6.5", "7.0"] and listed[0].builtin
    assert by_code is not None and by_code.score_max == 1600.0
    assert next_position == 2


async def test_entry_with_files_round_trips_and_is_found_by_serial(
    uow_factory: UowFactory,
) -> None:
    """Fields, dates, files and the (student, type, serial) lookup."""
    student, kind = new_id(), make_type("cefr")
    entry = make_entry(
        student,
        kind.id,
        level="B2",
        score=72.5,
        serial="C-1",
        source=EntrySource.EMIS,
        issued_at=date(2025, 3, 15),
    )
    file = EntryFile(new_id(), entry.id, "a.pdf", 10, "application/pdf")
    async with uow_factory() as uow:
        await uow.types.add(kind)
        await uow.entries.add(entry)
        await uow.entries.add_file(file)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.entries.find_by_serial(student, kind.id, "C-1")
        of_file = await uow.entries.entry_of_file(file.id)
        missing = await uow.entries.find_by_serial(new_id(), kind.id, "C-1")

    assert found is not None
    assert (found.level, found.score, found.source, found.issued_at) == (
        "B2",
        72.5,
        EntrySource.EMIS,
        date(2025, 3, 15),
    )
    assert found.files == [file]
    assert of_file is not None and of_file.id == entry.id
    assert missing is None


async def test_save_removing_a_file_and_deleting_an_entry(
    uow_factory: UowFactory,
) -> None:
    """Edits persist; a detached file is gone; deleting the entry drops its files."""
    student, kind = new_id(), make_type("sat")
    entry = make_entry(student, kind.id, score=1200.0)
    file = EntryFile(new_id(), entry.id, "a.png", 5, "image/png")
    async with uow_factory() as uow:
        await uow.types.add(kind)
        await uow.entries.add(entry)
        await uow.entries.add_file(file)
        entry.score = 1300.0
        await uow.entries.save(entry)
        await uow.commit()
    async with uow_factory() as uow:
        await uow.entries.remove_file(file.id)
        await uow.commit()
    async with uow_factory() as uow:
        [mine] = await uow.entries.list_for_student(student)
        assert (mine.score, mine.files) == (1300.0, [])
        assert await uow.entries.count_for_type(kind.id) == 1
        await uow.entries.delete(entry.id)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.entries.list_for_student(student) == []


async def test_query_filters_pages_and_counts(uow_factory: UowFactory) -> None:
    """Students, type, level and subject filters; the total ignores paging."""
    ann, bob, other = new_id(), new_id(), new_id()
    cefr, sat = make_type("cefr"), make_type("sat")
    async with uow_factory() as uow:
        await uow.types.add(cefr)
        await uow.types.add(sat)
        await uow.entries.add(make_entry(ann, cefr.id, level="B2", subject="English"))
        await uow.entries.add(make_entry(ann, sat.id))
        await uow.entries.add(make_entry(bob, cefr.id, level="B1", subject="German"))
        await uow.entries.add(make_entry(other, cefr.id, level="B2"))
        await uow.commit()

    async with uow_factory() as uow:
        everyone, total = await uow.entries.query(
            EntryFilter([ann, bob]), limit=None, offset=0
        )
        page, page_total = await uow.entries.query(
            EntryFilter([ann, bob]), limit=1, offset=1
        )
        of_type, _ = await uow.entries.query(
            EntryFilter([ann, bob], type_id=sat.id), limit=None, offset=0
        )
        of_level, _ = await uow.entries.query(
            EntryFilter([ann, bob], level="B1"), limit=None, offset=0
        )
        of_subject, _ = await uow.entries.query(
            EntryFilter([ann, bob], subject="engl"), limit=None, offset=0
        )
        nobody = await uow.entries.query(EntryFilter([]), limit=None, offset=0)

    assert (len(everyone), total, len(page), page_total) == (3, 3, 1, 3)
    assert [e.type_id for e in of_type] == [sat.id]
    assert [e.student_id for e in of_level] == [bob]
    assert [e.student_id for e in of_subject] == [ann]
    assert nobody == ([], 0)
