"""FILE-6, UF-SYS-07, UF-SYS-08 (files part): cleanup, warnings, purge, sweep."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.used_by import UsedBy
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.notifications import NotificationType
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import PNG_BYTES, sha256_b64, upload_and_complete, upload_ready


async def _student_file(fakes: FilesFakes, actor: Actor, name: str = "a.txt") -> UUID:
    return await upload_ready(
        fakes, actor, name=name, data=b"some text", content_type="text/plain"
    )


def _set_today(fakes: FilesFakes, day: date) -> None:
    fakes.clock.set(datetime(day.year, day.month, day.day, 9, 0, tzinfo=UTC))


async def test_cleanup_deletes_objects_and_sidecars_of_an_expired_term(
    fakes: FilesFakes, student: Actor
) -> None:
    """UF-SYS-07 step 2: term end + 14 days passed -> object, text and row state go."""
    term = uuid4()
    fakes.terms.current = term
    fakes.terms.ends[term] = date(2027, 1, 15)
    file_id = await _student_file(fakes, student)
    row = fakes.db.row(file_id)
    assert row.text_key in fakes.storage.objects
    _set_today(fakes, date(2027, 1, 30))

    deleted = await fakes.services.cleanup_expired.execute()

    assert deleted == 1
    assert row.key not in fakes.storage.objects
    assert row.text_key not in fakes.storage.objects
    after = fakes.db.row(file_id)
    assert after.status == FileStatus.DELETED
    assert after.text_bytes is None
    assert file_id not in fakes.db.store.texts


async def test_cleanup_keeps_files_until_the_expiry_day_is_over(
    fakes: FilesFakes, student: Actor
) -> None:
    """Students can download on the expiry day itself (2027-01-29)."""
    term = uuid4()
    fakes.terms.current = term
    fakes.terms.ends[term] = date(2027, 1, 15)
    file_id = await _student_file(fakes, student)
    _set_today(fakes, date(2027, 1, 29))

    assert await fakes.services.cleanup_expired.execute() == 0

    assert fakes.db.row(file_id).status == FileStatus.READY


async def test_cleanup_does_not_touch_the_current_term_or_staff_files(
    fakes: FilesFakes, student: Actor, teacher: Actor
) -> None:
    """Staff lesson materials are kept; later terms are kept."""
    old_term, new_term = uuid4(), uuid4()
    fakes.terms.ends[old_term] = date(2027, 1, 15)
    fakes.terms.ends[new_term] = date(2027, 6, 1)
    fakes.terms.current = new_term
    current = await _student_file(fakes, student)
    fakes.terms.current = None
    staff = await _student_file(fakes, teacher, "staff.txt")
    _set_today(fakes, date(2027, 2, 1))

    await fakes.services.cleanup_expired.execute()

    assert fakes.db.row(current).status == FileStatus.READY
    assert fakes.db.row(staff).status == FileStatus.READY


async def test_a_file_from_an_old_term_is_deleted_even_if_it_is_still_used(
    fakes: FilesFakes, student: Actor
) -> None:
    """UF-SYS-07 2a: it belongs to the term it was uploaded in."""
    term = uuid4()
    fakes.terms.current = term
    fakes.terms.ends[term] = date(2027, 1, 15)
    file_id = await _student_file(fakes, student)
    fakes.usage.usage[file_id] = [UsedBy("lesson", uuid4(), "Physics")]
    _set_today(fakes, date(2027, 2, 1))

    await fakes.services.cleanup_expired.execute()

    assert fakes.db.row(file_id).status == FileStatus.DELETED


async def test_cleanup_deletes_files_past_their_own_expiry_such_as_mail(
    fakes: FilesFakes,
) -> None:
    """FILE-6: mail files are deleted after 30 days."""
    ref = await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.MAIL,
        purpose=FilePurpose.MAIL,
        name="a.pdf",
        data=b"mail attachment",
        expires_days=30,
    )
    fakes.clock.advance(days=29)
    assert await fakes.services.cleanup_expired.execute() == 0

    fakes.clock.advance(days=2)
    assert await fakes.services.cleanup_expired.execute() == 1

    assert fakes.db.row(ref.id).status == FileStatus.DELETED
    assert fakes.db.row(ref.id).key not in fakes.storage.objects


async def test_cleanup_deletes_in_batches_of_at_most_1000_keys(
    fakes: FilesFakes,
) -> None:
    """README -> File storage: DeleteObjects takes 1000 keys per call."""
    for index in range(600):
        await fakes.services.public.store_bytes(
            owner_id=uuid4(),
            scope=FileScope.MAIL,
            purpose=FilePurpose.MAIL,
            name=f"{index}.bin",
            data=b"x",
            expires_days=1,
        )
    fakes.clock.advance(days=2)

    deleted = await fakes.services.cleanup_expired.execute()

    assert deleted == 600
    assert max(len(batch) for batch in fakes.storage.delete_batches) <= 1000
    assert len(fakes.storage.delete_batches) == 2


async def test_cleanup_twice_deletes_nothing_more(
    fakes: FilesFakes,
) -> None:
    """The job is idempotent."""
    await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.MAIL,
        purpose=FilePurpose.MAIL,
        name="a.bin",
        data=b"x",
        expires_days=1,
    )
    fakes.clock.advance(days=2)

    assert await fakes.services.cleanup_expired.execute() == 1
    assert await fakes.services.cleanup_expired.execute() == 0


async def test_warning_goes_to_each_owner_seven_days_before_the_expiry_day(
    fakes: FilesFakes, student: Actor, make_actor: Callable[..., Actor]
) -> None:
    """UF-SYS-07 step 1: one files_expiring notification per owner and term."""
    term = uuid4()
    fakes.terms.current = term
    fakes.terms.ends[term] = date(2027, 1, 15)
    await _student_file(fakes, student, "a.txt")
    await _student_file(fakes, student, "b.txt")
    other = make_actor(*student.roles)
    await _student_file(fakes, other, "c.txt")
    _set_today(fakes, date(2027, 1, 22))

    queued = await fakes.services.warn_expiring.execute()

    assert queued == 2
    drafts = {d.user_id: d for d in fakes.db.log.notifications}
    assert set(drafts) == {student.user_id, other.user_id}
    mine = drafts[student.user_id]
    assert mine.type == NotificationType.FILES_EXPIRING
    assert mine.payload == {
        "term_id": str(term),
        "expires_on": "2027-01-29",
        "files_count": 2,
    }
    assert mine.dedupe_key == f"files-expiring:{term}:{student.user_id}"


async def test_no_warning_before_the_window_or_after_the_expiry_day(
    fakes: FilesFakes, student: Actor
) -> None:
    """Only inside the seven days before the expiry day."""
    term = uuid4()
    fakes.terms.current = term
    fakes.terms.ends[term] = date(2027, 1, 15)
    await _student_file(fakes, student)

    for day in (date(2027, 1, 21), date(2027, 1, 30)):
        _set_today(fakes, day)
        assert await fakes.services.warn_expiring.execute() == 0

    assert fakes.db.log.notifications == []


async def test_pending_uploads_older_than_a_day_are_purged_with_their_object(
    fakes: FilesFakes, student: Actor
) -> None:
    """FILE-6: pending rows older than 24 hours are removed."""
    old = await fakes.services.request_upload.execute(
        student,
        name="a.png",
        size=len(PNG_BYTES),
        content_type="image/png",
        sha256_b64=sha256_b64(PNG_BYTES),
        purpose=FilePurpose.LINK,
    )
    fakes.storage.upload(old.upload, PNG_BYTES)
    fakes.clock.advance(hours=23)
    fresh = await fakes.services.request_upload.execute(
        student,
        name="b.png",
        size=len(PNG_BYTES),
        content_type="image/png",
        sha256_b64=sha256_b64(PNG_BYTES),
        purpose=FilePurpose.LINK,
    )
    fakes.clock.advance(hours=2)

    purged = await fakes.services.purge_pending.execute()

    assert purged == 1
    assert old.view.file.id not in {r.id for r in fakes.db.all_rows()}
    assert fresh.view.file.id in {r.id for r in fakes.db.all_rows()}
    assert all(not key.endswith(".png") for key in fakes.storage.objects)


async def test_rejected_files_disappear_a_day_after_the_rejection(
    fakes: FilesFakes, student: Actor
) -> None:
    """UF-WEB-18 2b: the row shows the reason, then disappears after 24 hours."""
    view = await upload_and_complete(
        fakes,
        student,
        name="a.pdf",
        data=PNG_BYTES,
        content_type="application/pdf",
    )
    assert view.file.status == FileStatus.REJECTED
    fakes.clock.advance(hours=23)
    assert await fakes.services.purge_pending.execute() == 0

    fakes.clock.advance(hours=2)

    assert await fakes.services.purge_pending.execute() == 1
    assert fakes.db.all_rows() == []


async def test_sweep_restarts_files_stuck_in_processing_for_ten_minutes(
    fakes: FilesFakes, student: Actor
) -> None:
    """Every 10 minutes: 'processing' for more than 10 minutes is kicked again."""
    stuck = await upload_and_complete(
        fakes, student, name="a.txt", data=b"stuck", content_type="text/plain"
    )
    fakes.kicker.calls.clear()
    fakes.clock.advance(minutes=9)
    assert await fakes.services.sweep_processing.execute() == 0

    fakes.clock.advance(minutes=2)
    kicked = await fakes.services.sweep_processing.execute()

    assert kicked == 1
    assert fakes.kicker.calls == [("files.process", {"file_id": str(stuck.file.id)})]


async def test_sweep_ignores_files_that_finished_processing(
    fakes: FilesFakes, student: Actor
) -> None:
    """Ready files are not restarted."""
    await _student_file(fakes, student)
    fakes.kicker.calls.clear()
    fakes.clock.advance(hours=1)

    assert await fakes.services.sweep_processing.execute() == 0
    assert fakes.kicker.calls == []


async def test_delete_owner_removes_every_file_of_the_user_only(
    fakes: FilesFakes, student: Actor, make_actor: Callable[..., Actor]
) -> None:
    """Task files.delete_owner: account deletion."""
    mine = [await _student_file(fakes, student, f"{i}.txt") for i in range(3)]
    other = await _student_file(fakes, make_actor(*student.roles), "other.txt")

    deleted = await fakes.services.delete_owner_files.execute(student.user_id)

    assert deleted == 3
    for file_id in mine:
        assert fakes.db.row(file_id).status == FileStatus.DELETED
        assert fakes.db.row(file_id).key not in fakes.storage.objects
    assert fakes.db.row(other).status == FileStatus.READY
