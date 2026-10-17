"""A student's own certificates and files, with the files module's quota."""

from app.modules.certificates.domain.errors import (
    CertificateEntryNotFoundError,
    CertificateFileNotFoundError,
    CertificateInvalidError,
    CertificateTypeNotFoundError,
)
from app.modules.files.domain.errors import QuotaExceededError, TypeNotAllowedError
from app.shared.ids import new_id
from tests.certificates.conftest import CertificatesHarness

import pytest


async def test_a_student_records_a_certificate(h: CertificatesHarness) -> None:
    """The entry is stored with the given values and the manual source."""
    kind = await h.add_type("ielts", levels=["6.0", "6.5", "7.0"])

    entry = await h.services.create_entry.execute(
        h.ann.id, kind.id, {"level": " 6.5 ", "year": 2026, "serial": ""}
    )

    mine = await h.services.list_my_entries.execute(h.ann.id)
    assert [(e.level, e.year, e.serial, e.source.value) for e in mine] == [
        ("6.5", 2026, None, "manual")
    ]
    assert entry.id == mine[0].id


async def test_an_unknown_type_is_refused(h: CertificatesHarness) -> None:
    """The type must exist."""
    with pytest.raises(CertificateTypeNotFoundError):
        await h.services.create_entry.execute(h.ann.id, new_id(), {})


@pytest.mark.parametrize(
    "values",
    [
        {"level": "9.9"},
        {"score": 1700},
        {"percent": 101},
        {"year": 1800},
    ],
)
async def test_values_outside_the_type_are_refused(
    h: CertificatesHarness, values: dict[str, object]
) -> None:
    """Level not in the type, score or percent out of range, odd year: 422."""
    kind = await h.add_type(
        "sat", levels=["6.5"], score_min=400, score_max=1600, asks_score=True
    )

    with pytest.raises(CertificateInvalidError):
        await h.services.create_entry.execute(h.ann.id, kind.id, values)


async def test_a_student_edits_only_the_sent_fields(h: CertificatesHarness) -> None:
    """Fields not in the patch keep their value."""
    kind = await h.add_type("sat", score_min=400, score_max=1600)
    entry_id = await h.add_entry(h.ann, kind, score=1300, subject="Math")

    changed = await h.services.update_entry.execute(h.ann.id, entry_id, {"score": 1400})

    assert (changed.score, changed.subject) == (1400, "Math")


async def test_someone_elses_entry_is_not_found(h: CertificatesHarness) -> None:
    """Edit, delete and file upload answer 'not found' for another student's entry."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)

    with pytest.raises(CertificateEntryNotFoundError):
        await h.services.update_entry.execute(h.bob.id, entry_id, {})
    with pytest.raises(CertificateEntryNotFoundError):
        await h.services.delete_entry.execute(h.bob.id, entry_id)
    with pytest.raises(CertificateEntryNotFoundError):
        await h.services.add_entry_file.execute(
            h.bob.id, entry_id, name="a.pdf", data=b"x"
        )


async def test_a_file_is_stored_for_the_student_and_listed(
    h: CertificatesHarness,
) -> None:
    """The file belongs to the student (their quota) and is attached to the entry."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)

    file_id = await h.add_file(h.ann, entry_id, "Scan.PDF")

    stored = h.files.files[file_id]
    assert (stored.owner_id, stored.purpose.value) == (h.ann.id, "certificate")
    [mine] = await h.services.list_my_entries.execute(h.ann.id)
    assert [(f.id, f.name) for f in mine.files] == [(file_id, "Scan.PDF")]


async def test_a_file_over_the_quota_is_refused_and_not_attached(
    h: CertificatesHarness,
) -> None:
    """The files module's quota error passes through; nothing is attached."""
    h.files.quota = 3
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)

    with pytest.raises(QuotaExceededError):
        await h.services.add_entry_file.execute(
            h.ann.id, entry_id, name="a.pdf", data=b"abcd"
        )

    [mine] = await h.services.list_my_entries.execute(h.ann.id)
    assert mine.files == []


async def test_a_file_of_a_wrong_type_is_refused(h: CertificatesHarness) -> None:
    """Only the allowed extensions pass (the files module decides)."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)

    with pytest.raises(TypeNotAllowedError):
        await h.services.add_entry_file.execute(
            h.ann.id, entry_id, name="virus.exe", data=b"x"
        )


async def test_removing_a_file_frees_the_storage(h: CertificatesHarness) -> None:
    """The row is detached and the stored object deleted."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)
    file_id = await h.add_file(h.ann, entry_id)

    await h.services.remove_entry_file.execute(h.ann.id, entry_id, file_id)

    assert h.files.deleted == [file_id]
    with pytest.raises(CertificateFileNotFoundError):
        await h.services.remove_entry_file.execute(h.ann.id, entry_id, file_id)


async def test_deleting_an_entry_deletes_its_files(h: CertificatesHarness) -> None:
    """Both files are removed from the files module."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)
    first = await h.add_file(h.ann, entry_id, "a.pdf")
    second = await h.add_file(h.ann, entry_id, "b.png")

    await h.services.delete_entry.execute(h.ann.id, entry_id)

    assert await h.services.list_my_entries.execute(h.ann.id) == []
    assert set(h.files.deleted) == {first, second}
