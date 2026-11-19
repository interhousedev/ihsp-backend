"""Face and profile photos are system files: hidden from the owner, still owned."""

from uuid import UUID

from app.modules.files.domain.status import FileStatus
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import PNG_BYTES, upload_ready

PHOTO_NAME = "face.png"


async def _photo(fakes: FilesFakes, actor: Actor, name: str = PHOTO_NAME) -> UUID:
    ref = await fakes.services.public.store_bytes(
        owner_id=actor.user_id,
        scope=FileScope.STAFF,
        purpose=FilePurpose.USER_PHOTO,
        name=name,
        data=PNG_BYTES,
    )
    return ref.id


async def _note(fakes: FilesFakes, actor: Actor) -> UUID:
    return await upload_ready(
        fakes, actor, name="a.txt", data=b"hello", content_type="text/plain"
    )


async def test_my_files_hides_face_and_profile_photos(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """FILES-FACE-1: only the real file is listed."""
    note = await _note(fakes, teacher)
    await _photo(fakes, teacher, "face.png")
    await _photo(fakes, teacher, "photo.png")

    page = await fakes.services.list_my_files.execute(teacher)

    assert [item.file.id for item in page.items] == [note]


async def test_owned_files_hide_system_photos(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """FILES-FACE-2: other modules' owner lists skip system files too."""
    note = await _note(fakes, teacher)
    await _photo(fakes, teacher)

    owned = await fakes.services.list_owned_files.execute(teacher.user_id, limit=10)

    assert [ref.id for ref in owned] == [note]


async def test_usage_equals_the_sum_of_listed_files(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """FILES-FACE-3: the quota bar ignores system photos."""
    await _note(fakes, teacher)
    await _photo(fakes, teacher)

    page = await fakes.services.list_my_files.execute(teacher)
    usage = await fakes.services.storage_usage.execute(teacher)

    assert usage.used_bytes == sum(item.file.byte_size for item in page.items)
    assert usage.used_bytes == len(b"hello")


async def test_system_photos_stay_in_the_export_and_are_erased_with_the_account(
    fakes: FilesFakes, teacher: Actor
) -> None:
    """FILES-FACE-4: the row is still the owner's, and erasure deletes it."""
    photo = await _photo(fakes, teacher)
    async with fakes.db.uow() as uow:
        everything = await uow.files.list_for_owner_all(teacher.user_id, 100)
    assert [f.id for f in everything] == [photo]

    deleted = await fakes.services.delete_owner_files.execute(teacher.user_id)

    assert deleted == 1
    assert fakes.db.row(photo).status == FileStatus.DELETED
    assert fakes.db.row(photo).key not in fakes.storage.objects
