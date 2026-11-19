"""One-off: give users who enrolled a face before the copy existed a profile photo."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.faces.ports.profile_photo import ProfilePhotos
from app.shared.contracts.files import FilesApi

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EnrolledFace:
    """A user with an enrolled face and the file that holds the face image."""

    user_id: UUID
    photo_file_id: UUID


class EnrolledFaces(Protocol):
    """Port: every enrolled face."""

    async def all(self) -> list[EnrolledFace]:
        """Return every enrolled face."""
        ...


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """How many users got a photo, were left alone, or could not be done."""

    set: int
    skipped: int
    failed: int


@dataclass(frozen=True, slots=True)
class BackfillProfilePhotos:
    """Copies the enrolled face to the profile photo of users who have none.

    A user with any photo (a face copy or one they or an administrator chose) is
    skipped, so the command can run again and never overwrites a chosen photo.
    """

    faces: EnrolledFaces
    files: FilesApi
    profile_photos: ProfilePhotos

    async def execute(self) -> BackfillResult:
        """Copy the faces; one user's failure is counted and never stops the rest."""
        done = skipped = failed = 0
        for face in await self.faces.all():
            try:
                if await self.profile_photos.source(face.user_id) != "none":
                    skipped += 1
                    continue
                data = await self.files.read_bytes(face.photo_file_id)
                await self.profile_photos.set_photo(face.user_id, data)
                done += 1
            except Exception:  # count it and go on; never log who it was
                failed += 1
                log.warning("face_photo_backfill_failed", exc_info=True)
        return BackfillResult(set=done, skipped=skipped, failed=failed)
