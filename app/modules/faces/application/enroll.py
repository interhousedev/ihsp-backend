"""Shared core of the face uploads: check, embed, store profile and photo."""

from uuid import UUID

from app.modules.faces.domain.errors import (
    FaceLockedError,
    FaceNotFoundError,
    NoFaceError,
)
from app.modules.faces.domain.image import SNIFF_BYTES, check_image
from app.modules.faces.domain.models import FaceProfile
from app.modules.faces.ports.engine import FaceEngine, ImageSniffer
from app.modules.faces.ports.profile_photo import ProfilePhotos
from app.modules.faces.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope

import structlog

log = structlog.get_logger(__name__)


class FaceEnroller:
    """Stores a face for a user; students may not replace one that staff set.

    The new face also becomes the user's profile photo, so the avatars show it.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        engine: FaceEngine,
        sniffer: ImageSniffer,
        files: FilesApi,
        profile_photos: ProfilePhotos,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._engine = engine
        self._sniffer = sniffer
        self._files = files
        self._profile_photos = profile_photos
        self._clock = clock

    async def enroll(
        self, user_id: UUID, *, uploaded_by: UUID, data: bytes, by_staff: bool
    ) -> FaceProfile:
        """Check the image, find the one face and save it; staff lock the result."""
        sniffed = await self._sniffer.sniff(data[:SNIFF_BYTES])
        check_image(data, sniffed)
        async with self._uow_factory() as uow:
            current = await uow.profiles.get(user_id)
        if current is not None and current.locked and not by_staff:
            raise FaceLockedError()
        embedding = await self._engine.embed(data)
        if embedding is None:
            raise NoFaceError()
        stored = await self._files.store_bytes(
            owner_id=user_id,
            scope=FileScope.SYSTEM,
            purpose=FilePurpose.USER_PHOTO,
            name="face.png" if sniffed == "image/png" else "face.jpg",
            data=data,
        )
        profile = FaceProfile(
            user_id=user_id,
            embedding=embedding,
            photo_file_id=stored.id,
            uploaded_by=uploaded_by,
            locked=by_staff,
            updated_at=self._clock.now(),
        )
        try:
            async with self._uow_factory() as uow:
                latest = await uow.profiles.get(user_id)
                if latest is not None and latest.locked and not by_staff:
                    raise FaceLockedError()
                await uow.profiles.save(profile)
                await uow.commit()
        except BaseException:
            await self._files.delete_file(stored.id)
            raise
        if current is not None:
            await self._files.delete_file(current.photo_file_id)
        await self._set_profile_photo(user_id, data)
        return profile

    async def _set_profile_photo(self, user_id: UUID, data: bytes) -> None:
        """Copy the face to the profile photo; the face is saved even if this fails.

        The face is the profile photo until the user uploads another one: only an
        empty photo or an earlier face copy is replaced, never a chosen photo.
        """
        try:
            if await self._profile_photos.source(user_id) == "other":
                return
            await self._profile_photos.set_photo(user_id, data)
        except Exception:  # the face is committed; never fail the upload for this
            log.warning(
                "face_profile_photo_failed", user_id=str(user_id), exc_info=True
            )

    async def remove(self, user_id: UUID, *, by_staff: bool) -> None:
        """Delete the face; a student cannot delete one that staff set."""
        async with self._uow_factory() as uow:
            current = await uow.profiles.get(user_id)
            if current is None:
                raise FaceNotFoundError()
            if current.locked and not by_staff:
                raise FaceLockedError()
            await uow.profiles.delete(user_id)
            await uow.commit()
        await self._files.delete_file(current.photo_file_id)
        await self._remove_profile_photo(user_id)

    async def _remove_profile_photo(self, user_id: UUID) -> None:
        """Remove the profile photo when it is the face copy; failures are logged."""
        try:
            if await self._profile_photos.source(user_id) == "face":
                await self._profile_photos.remove_photo(user_id)
        except Exception:  # the face is already gone; never fail the removal
            log.warning(
                "face_profile_photo_remove_failed", user_id=str(user_id), exc_info=True
            )
