"""WEB-21, UF-WEB-18: My files — list, rename, delete, quota bar."""

from collections.abc import Callable
from datetime import date
from uuid import UUID, uuid4

from app.modules.files.domain.errors import (
    StoredFileNotFoundError,
    TypeNotAllowedError,
)
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.used_by import UsedBy
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.files.services import DEFAULT_LIMITS, FilesFakes
from tests.files.helpers import PNG_BYTES, make_pdf, upload_ready

import pytest


async def _txt(
    fakes: FilesFakes,
    actor: Actor,
    name: str,
    purpose: FilePurpose = FilePurpose.LINK,
) -> UUID:
    return await upload_ready(
        fakes,
        actor,
        name=name,
        data=b"text of " + name.encode(),
        content_type="text/plain",
        purpose=purpose,
    )


async def test_my_files_lists_newest_first_with_a_cursor(
    fakes: FilesFakes, student: Actor
) -> None:
    """Cursor pagination, newest first."""
    ids = []
    for index in range(5):
        fakes.clock.advance(minutes=1)
        ids.append(await _txt(fakes, student, f"{index}.txt"))

    first = await fakes.services.list_my_files.execute(student, limit=2)
    second = await fakes.services.list_my_files.execute(
        student, limit=2, cursor=first.next_cursor
    )
    third = await fakes.services.list_my_files.execute(
        student, limit=2, cursor=second.next_cursor
    )

    assert [v.file.id for v in first.items] == [ids[4], ids[3]]
    assert [v.file.id for v in second.items] == [ids[2], ids[1]]
    assert [v.file.id for v in third.items] == [ids[0]]
    assert third.next_cursor is None


async def test_my_files_filters_by_purpose_and_hides_other_users(
    fakes: FilesFakes, student: Actor, make_actor: Callable[..., Actor]
) -> None:
    """``?purpose=`` and only the caller's own files."""
    link = await _txt(fakes, student, "link.txt", FilePurpose.LINK)
    upload = await _txt(fakes, student, "chat.txt", FilePurpose.AI_UPLOAD)
    await _txt(fakes, make_actor(*student.roles), "foreign.txt")

    everything = await fakes.services.list_my_files.execute(student)
    only_chat = await fakes.services.list_my_files.execute(
        student, purpose=FilePurpose.AI_UPLOAD
    )

    assert {v.file.id for v in everything.items} == {link, upload}
    assert [v.file.id for v in only_chat.items] == [upload]


async def test_my_files_shows_used_by_and_the_expiry_date(
    fakes: FilesFakes, student: Actor
) -> None:
    """UF-WEB-18 step 1: used-by links and when the term's files are deleted."""
    term = uuid4()
    fakes.terms.current = term
    fakes.terms.ends[term] = date(2027, 1, 15)
    file_id = await _txt(fakes, student, "a.txt")
    used = UsedBy(kind="link", id=uuid4(), label="s.ihsu.uz/Ab3")
    fakes.usage.usage[file_id] = [used]

    page = await fakes.services.list_my_files.execute(student)

    view = page.items[0]
    assert view.expires_on == date(2027, 1, 29)
    assert view.used_by == [used]
    assert view.assistant_ready is True


async def test_pending_and_deleted_files_are_not_listed(
    fakes: FilesFakes, student: Actor
) -> None:
    """Only files that exist are shown."""
    kept = await _txt(fakes, student, "kept.txt")
    gone = await _txt(fakes, student, "gone.txt")
    await fakes.services.delete_file.execute(student, gone)

    page = await fakes.services.list_my_files.execute(student)

    assert [v.file.id for v in page.items] == [kept]


async def test_rename_changes_the_name_but_not_the_key(
    fakes: FilesFakes, student: Actor
) -> None:
    """UF-WEB-18 step 4."""
    file_id = await _txt(fakes, student, "old.txt")
    key = fakes.db.row(file_id).key

    view = await fakes.services.rename_file.execute(student, file_id, "new name.txt")

    assert view.file.name == "new name.txt"
    assert fakes.db.row(file_id).key == key


async def test_rename_cannot_change_the_extension(
    fakes: FilesFakes, student: Actor
) -> None:
    """A .txt cannot become an .exe."""
    file_id = await _txt(fakes, student, "old.txt")

    with pytest.raises(TypeNotAllowedError):
        await fakes.services.rename_file.execute(student, file_id, "old.exe")


async def test_only_the_owner_can_rename_or_delete(
    fakes: FilesFakes,
    student: Actor,
    admin: Actor,
    make_actor: Callable[..., Actor],
) -> None:
    """Owner operations hide the file from everyone else, administrators included."""
    file_id = await _txt(fakes, student, "a.txt")

    for other in (make_actor(*student.roles), admin):
        with pytest.raises(StoredFileNotFoundError):
            await fakes.services.rename_file.execute(other, file_id, "b.txt")
        with pytest.raises(StoredFileNotFoundError):
            await fakes.services.delete_file.execute(other, file_id)


async def test_delete_removes_objects_at_once_and_returns_used_by(
    fakes: FilesFakes, student: Actor
) -> None:
    """UF-WEB-18 4a: the warning lists what stops working."""
    file_id = await upload_ready(
        fakes,
        student,
        name="a.pdf",
        data=make_pdf("Delete me"),
        content_type="application/pdf",
    )
    row = fakes.db.row(file_id)
    used = [UsedBy(kind="lesson", id=uuid4(), label="Physics 2026-10-06")]
    fakes.usage.usage[file_id] = used
    assert row.text_key in fakes.storage.objects

    result = await fakes.services.delete_file.execute(student, file_id)

    assert result == used
    assert row.key not in fakes.storage.objects
    assert row.text_key not in fakes.storage.objects
    assert fakes.db.row(file_id).status == FileStatus.DELETED
    assert fakes.db.row(file_id).deleted_at == fakes.clock.now()
    assert fakes.db.row(file_id).text_bytes is None


async def test_a_deleted_file_cannot_be_deleted_again(
    fakes: FilesFakes, student: Actor
) -> None:
    """Deleting twice is NotFound."""
    file_id = await _txt(fakes, student, "a.txt")
    await fakes.services.delete_file.execute(student, file_id)

    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.delete_file.execute(student, file_id)


async def test_deleting_frees_quota(fakes: FilesFakes, student: Actor) -> None:
    """The quota counts live files only."""
    file_id = await _txt(fakes, student, "a.txt")
    before = await fakes.services.storage_usage.execute(student)

    await fakes.services.delete_file.execute(student, file_id)
    after = await fakes.services.storage_usage.execute(student)

    assert before.used_bytes > 0
    assert after.used_bytes == 0


async def test_course_and_mail_files_cannot_be_changed_by_owners(
    fakes: FilesFakes, student: Actor
) -> None:
    """Those scopes are managed by their own modules."""
    ref = await fakes.services.public.store_bytes(
        owner_id=student.user_id,
        scope=FileScope.COURSE,
        purpose=FilePurpose.LINK,
        name="cover.png",
        data=PNG_BYTES,
    )

    with pytest.raises(ForbiddenError):
        await fakes.services.delete_file.execute(student, ref.id)
    with pytest.raises(ForbiddenError):
        await fakes.services.rename_file.execute(student, ref.id, "x.png")


async def test_storage_usage_for_a_student_shows_the_term_and_expiry(
    fakes: FilesFakes, student: Actor
) -> None:
    """UF-WEB-18 step 1: 'N of 1.5 GB' and 'files are deleted on …'."""
    term = uuid4()
    fakes.terms.current = term
    fakes.terms.ends[term] = date(2027, 1, 15)
    await _txt(fakes, student, "a.txt")

    usage = await fakes.services.storage_usage.execute(student)

    assert usage.used_bytes == len(b"text of a.txt")
    assert usage.quota_bytes == DEFAULT_LIMITS.student_quota_bytes
    assert usage.term_id == term
    assert usage.expires_on == date(2027, 1, 29)


async def test_storage_usage_for_staff_has_the_staff_quota_and_no_expiry(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """FILE-5: staff 10 GB, no term."""
    fakes.terms.current = uuid4()

    usage = await fakes.services.storage_usage.execute(teacher)

    assert usage.quota_bytes == DEFAULT_LIMITS.staff_quota_bytes
    assert usage.term_id is None
    assert usage.expires_on is None


async def test_check_access_allows_the_owner_and_administrators_only(
    fakes: FilesFakes,
    student: Actor,
    admin: Actor,
    teacher: Actor,
    make_actor: Callable[..., Actor],
) -> None:
    """FilesApiImpl.check_access: owner or admin; never for deleted or unknown."""
    file_id = await _txt(fakes, student, "a.txt")
    api = fakes.services.public

    assert await api.check_access(file_id, student) is True
    assert await api.check_access(file_id, admin) is True
    assert await api.check_access(file_id, teacher) is False
    assert await api.check_access(file_id, make_actor(*student.roles)) is False
    assert await api.check_access(uuid4(), admin) is False
    await fakes.services.delete_file.execute(student, file_id)
    assert await api.check_access(file_id, student) is False


async def test_get_and_get_many_return_refs_including_deleted_files(
    fakes: FilesFakes, student: Actor
) -> None:
    """Links need the status 'deleted' to answer 410; unknown ids are skipped."""
    kept = await _txt(fakes, student, "kept.txt")
    gone = await _txt(fakes, student, "gone.txt")
    await fakes.services.delete_file.execute(student, gone)
    api = fakes.services.public

    ref = await api.get(kept)
    refs = await api.get_many([kept, gone, uuid4()])

    assert ref is not None
    assert (ref.name, ref.status, ref.purpose, ref.scope) == (
        "kept.txt",
        "ready",
        FilePurpose.LINK,
        FileScope.STUDENT,
    )
    assert set(refs) == {kept, gone}
    assert refs[gone].status == "deleted"
    assert await api.get(uuid4()) is None
