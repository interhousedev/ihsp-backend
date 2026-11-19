"""ID-PHOTO: the one-off copy of enrolled faces to profile photos."""

from uuid import UUID

from app.modules.faces.application.backfill_profile_photos import (
    BackfillProfilePhotos,
    EnrolledFace,
)
from app.shared.ids import new_id
from tests.fakes.faces.uow import FakeProfilePhotos

FACE = b"\x89PNG\r\n\x1a\nface"


class FakeEnrolled:
    """The enrolled faces and the bytes of their files."""

    def __init__(self) -> None:
        """No faces yet."""
        self.faces: list[EnrolledFace] = []
        self.content: dict[UUID, bytes] = {}

    def enroll(self, data: bytes = FACE) -> EnrolledFace:
        """Add a user with a face file."""
        face = EnrolledFace(user_id=new_id(), photo_file_id=new_id())
        self.faces.append(face)
        self.content[face.photo_file_id] = data
        return face

    async def all(self) -> list[EnrolledFace]:
        """Return every enrolled face."""
        return list(self.faces)

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the file or fail when it is gone."""
        return self.content[file_id]


def make() -> tuple[BackfillProfilePhotos, FakeEnrolled, FakeProfilePhotos]:
    """The use case over in-memory fakes."""
    enrolled = FakeEnrolled()
    photos = FakeProfilePhotos()
    use_case = BackfillProfilePhotos(
        faces=enrolled,
        files=enrolled,  # type: ignore[arg-type]
        profile_photos=photos,
    )
    return use_case, enrolled, photos


async def test_a_user_without_a_photo_gets_the_face() -> None:
    """ID-PHOTO-10: the enrolled face becomes the profile photo."""
    use_case, enrolled, photos = make()
    face = enrolled.enroll()

    result = await use_case.execute()

    assert (result.set, result.skipped, result.failed) == (1, 0, 0)
    assert photos.photos[face.user_id] == FACE
    assert photos.sources[face.user_id] == "face"


async def test_a_user_with_a_photo_is_skipped() -> None:
    """ID-PHOTO-11: a user who already has a face copy is left alone."""
    use_case, enrolled, photos = make()
    face = enrolled.enroll()
    photos.sources[face.user_id] = "face"
    photos.photos[face.user_id] = b"older face"

    result = await use_case.execute()

    assert (result.set, result.skipped, result.failed) == (0, 1, 0)
    assert photos.photos[face.user_id] == b"older face"


async def test_a_chosen_photo_is_never_overwritten() -> None:
    """ID-PHOTO-12: a photo of source "other" stays."""
    use_case, enrolled, photos = make()
    face = enrolled.enroll()
    photos.sources[face.user_id] = "other"
    photos.photos[face.user_id] = b"chosen"

    result = await use_case.execute()

    assert (result.set, result.skipped, result.failed) == (0, 1, 0)
    assert photos.photos[face.user_id] == b"chosen"
    assert photos.sources[face.user_id] == "other"


async def test_a_second_run_sets_nothing() -> None:
    """ID-PHOTO-13: the command is idempotent."""
    use_case, enrolled, _ = make()
    enrolled.enroll()
    enrolled.enroll()

    first = await use_case.execute()
    second = await use_case.execute()

    assert (first.set, first.skipped) == (2, 0)
    assert (second.set, second.skipped, second.failed) == (0, 2, 0)


async def test_failures_are_counted_and_do_not_stop_the_rest() -> None:
    """ID-PHOTO-14: a missing file counts as failed; the next user is still done."""
    use_case, enrolled, photos = make()
    broken = enrolled.enroll()
    del enrolled.content[broken.photo_file_id]
    fine = enrolled.enroll()

    result = await use_case.execute()

    assert (result.set, result.skipped, result.failed) == (1, 0, 1)
    assert fine.user_id in photos.photos
    assert broken.user_id not in photos.photos


async def test_a_rejected_photo_is_counted_as_failed() -> None:
    """ID-PHOTO-15: the photo store refusing the image counts as failed."""
    use_case, enrolled, photos = make()
    enrolled.enroll()
    photos.fail = True

    result = await use_case.execute()

    assert (result.set, result.skipped, result.failed) == (0, 0, 1)
