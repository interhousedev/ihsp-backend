"""Staff views: scope of curators, stats, ranking, file access and export."""

import io
import zipfile

from app.modules.certificates.application.export_entries import ExportItem
from app.modules.certificates.application.staff_scope import StaffFilters
from app.modules.certificates.domain.errors import (
    CertificateFileNotFoundError,
    NotCuratorError,
)
from app.shared.actor import Actor, Role
from tests.certificates.conftest import CertificatesHarness

import pytest


async def _world(h: CertificatesHarness) -> dict[str, object]:
    """Ann (A): two CEFR + volunteering; Bob (A): CEFR; Cid (B): CEFR."""
    cefr = await h.add_type("cefr", levels=["B1", "B2"], position=0)
    volunteering = await h.add_type("volunteering", position=1)
    await h.add_entry(h.ann, cefr, level="B2", subject="English")
    await h.add_entry(h.ann, cefr, level="B1", subject="German")
    await h.add_entry(h.ann, volunteering)
    await h.add_entry(h.bob, cefr, level="B2")
    await h.add_entry(h.cid, cefr, level="B2")
    return {"cefr": cefr, "volunteering": volunteering}


async def test_admin_sees_every_group(h: CertificatesHarness) -> None:
    """No filter: all five entries of all groups."""
    await _world(h)

    page = await h.services.list_staff_entries.execute(
        h.admin, StaffFilters(), limit=50, offset=0
    )

    assert page.total == 5
    assert {v.student.group_name for v in page.items} == {"2TN1", "2TN2"}


async def test_a_curator_sees_only_their_group(h: CertificatesHarness) -> None:
    """The other group's entries are not in the list."""
    await _world(h)

    page = await h.services.list_staff_entries.execute(
        h.curator, StaffFilters(), limit=50, offset=0
    )

    assert page.total == 4
    assert {v.student.id for v in page.items} == {h.ann.id, h.bob.id}


async def test_a_curator_of_another_group_is_forbidden(h: CertificatesHarness) -> None:
    """Asking for a group you do not curate is 403."""
    await _world(h)

    with pytest.raises(NotCuratorError):
        await h.services.list_staff_entries.execute(
            h.curator, StaffFilters(group_id=h.group_b), limit=50, offset=0
        )
    with pytest.raises(NotCuratorError):
        await h.services.list_staff_entries.execute(
            h.curator, StaffFilters(student_id=h.cid.id), limit=50, offset=0
        )


async def test_a_teacher_without_groups_is_forbidden(h: CertificatesHarness) -> None:
    """A teacher who curates nothing has no staff view."""
    nobody = Actor(user_id=h.ann.id, roles=frozenset({Role.TEACHER}))

    with pytest.raises(NotCuratorError):
        await h.services.list_staff_entries.execute(
            nobody, StaffFilters(), limit=50, offset=0
        )
    with pytest.raises(NotCuratorError):
        await h.services.list_staff_groups.execute(nobody)


async def test_filters_narrow_the_list_and_paging_reports_the_total(
    h: CertificatesHarness,
) -> None:
    """Subgroup, level, subject and student name filters apply; total ignores paging."""
    await _world(h)
    admin = h.admin

    half = await h.services.list_staff_entries.execute(
        admin, StaffFilters(subgroup="2"), limit=50, offset=0
    )
    level = await h.services.list_staff_entries.execute(
        admin, StaffFilters(level="B1"), limit=50, offset=0
    )
    subject = await h.services.list_staff_entries.execute(
        admin, StaffFilters(subject="germ"), limit=50, offset=0
    )
    named = await h.services.list_staff_entries.execute(
        admin, StaffFilters(q="cid"), limit=50, offset=0
    )
    paged = await h.services.list_staff_entries.execute(
        admin, StaffFilters(), limit=2, offset=4
    )

    assert [v.student.id for v in half.items] == [h.bob.id]
    assert level.total == 1
    assert subject.total == 1
    assert [v.student.id for v in named.items] == [h.cid.id]
    assert (len(paged.items), paged.total) == (1, 5)


async def test_staff_groups_for_the_dropdowns(h: CertificatesHarness) -> None:
    """Admin lists both groups; a curator only theirs, with subgroups."""
    admin_groups = await h.services.list_staff_groups.execute(h.admin)
    own = await h.services.list_staff_groups.execute(h.curator)

    assert [g.name for g in admin_groups] == ["2TN1", "2TN2"]
    assert [(g.name, g.subgroups) for g in own] == [("2TN1", ("1", "2"))]


async def test_stats_count_levels_per_group_with_a_dash_for_none(
    h: CertificatesHarness,
) -> None:
    """Levels follow the type's order; entries without a level count under the dash."""
    kinds = await _world(h)

    stats = await h.services.get_staff_stats.execute(h.admin, StaffFilters())

    by_type = {s.type_id: s for s in stats}
    cefr = by_type[kinds["cefr"].id]  # type: ignore[attr-defined]
    assert cefr.levels == ["B1", "B2"]
    assert [(g.group_name, g.counts) for g in cefr.groups] == [
        ("2TN1", {"B2": 2, "B1": 1}),
        ("2TN2", {"B2": 1}),
    ]
    volunteering = by_type[kinds["volunteering"].id]  # type: ignore[attr-defined]
    assert volunteering.levels == ["—"]
    assert volunteering.groups[0].counts == {"—": 1}


async def test_stats_of_a_curator_only_cover_their_group(
    h: CertificatesHarness,
) -> None:
    """The other group is not counted."""
    await _world(h)

    [cefr, _] = await h.services.get_staff_stats.execute(h.curator, StaffFilters())

    assert [g.group_name for g in cefr.groups] == ["2TN1"]


async def test_ranking_orders_students_by_count(h: CertificatesHarness) -> None:
    """Most certificates first; ties by name; the limit applies."""
    await _world(h)

    ranking = await h.services.get_staff_ranking.execute(
        h.admin, StaffFilters(), limit=2
    )

    assert [(r.name, r.group_name, r.count) for r in ranking] == [
        ("Ann Alpha", "2TN1", 3),
        ("Bob Beta", "2TN1", 1),
    ]


async def test_the_owner_admin_and_curator_open_a_file_but_not_other_curators(
    h: CertificatesHarness,
) -> None:
    """The URL goes to the owner, Administration and the group's curator."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)
    file_id = await h.add_file(h.ann, entry_id)
    download = h.services.get_file_download

    for actor in (h.student_actor(h.ann), h.admin, h.curator):
        assert (await download.execute(actor, file_id)).startswith(
            "https://storage.test/"
        )
    with pytest.raises(NotCuratorError):
        await download.execute(h.other_curator, file_id)
    with pytest.raises(NotCuratorError):
        await download.execute(h.student_actor(h.bob), file_id)
    with pytest.raises(CertificateFileNotFoundError):
        await download.execute(h.admin, h.ann.id)


async def _unzip(h: CertificatesHarness, items: list[ExportItem]) -> dict[str, bytes]:
    chunks = [c async for c in h.services.export_entries.stream(items)]
    with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        assert archive.testzip() is None
        return {n: archive.read(n) for n in archive.namelist()}


async def test_export_names_files_group_student_filename_and_dedupes(
    h: CertificatesHarness,
) -> None:
    """Two files named alike get ' (2)'; contents are the stored bytes."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.ann, kind)
    other_entry = await h.add_entry(h.ann, kind)
    first = await h.add_file(h.ann, entry_id, "scan.pdf")
    second = await h.add_file(h.ann, other_entry, "scan.pdf")
    h.files.objects[second] = b"second"

    items = await h.services.export_entries.plan(
        h.admin, file_ids=[first, second], filters=None
    )
    content = await _unzip(h, items)

    assert set(content) == {"2TN1-Ann Alpha-scan.pdf", "2TN1-Ann Alpha-scan (2).pdf"}
    assert sorted(content.values()) == [b"data", b"second"]


async def test_export_by_filters_takes_every_file_in_scope(
    h: CertificatesHarness,
) -> None:
    """The filters pick entries; a curator's export never includes other groups."""
    kind = await h.add_type("sat")
    for student in (h.ann, h.cid):
        entry_id = await h.add_entry(student, kind)
        await h.add_file(student, entry_id)

    items = await h.services.export_entries.plan(
        h.curator, file_ids=None, filters=StaffFilters(type_id=kind.id)
    )
    content = await _unzip(h, items)

    assert list(content) == ["2TN1-Ann Alpha-scan.pdf"]


async def test_a_curator_cannot_export_another_groups_file(
    h: CertificatesHarness,
) -> None:
    """Asking for a file of a student outside the scope is 403."""
    kind = await h.add_type("sat")
    entry_id = await h.add_entry(h.cid, kind)
    file_id = await h.add_file(h.cid, entry_id)

    with pytest.raises(NotCuratorError):
        await h.services.export_entries.plan(
            h.curator, file_ids=[file_id], filters=None
        )


async def test_an_export_without_files_is_not_found(h: CertificatesHarness) -> None:
    """Nothing to pack is an error rather than an empty archive."""
    await _world(h)

    with pytest.raises(CertificateFileNotFoundError):
        await h.services.export_entries.plan(h.admin, file_ids=None, filters=None)
