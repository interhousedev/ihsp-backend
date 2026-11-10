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
from app.modules.faces.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope


class FaceEnroller:
    """Stores a face for a user; students may not replace one that staff set."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        engine: FaceEngine,
        sniffer: ImageSniffer,
        files: FilesApi,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._engine = engine
        self._sniffer = sniffer
        self._files = files
        self._clock = clock

    async def enroll(
        self, user_id: UUID, *, uploaded_by: UUID, data: bytes, by_staff: bool
    ) -> FaceProfile:
        """Check the image, find the one face and save it; staff lock the result."""
        check_image(data, await self._sniffer.sniff(data[:SNIFF_BYTES]))
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
            name="face",
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
        return profile

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
