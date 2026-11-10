"""Own face: read it, upload it, delete it (students and any staff member alike)."""

from uuid import UUID

from app.modules.faces.application.enroll import FaceEnroller
from app.modules.faces.application.views import FaceView
from app.modules.faces.domain.errors import FaceNotFoundError
from app.modules.faces.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FilesApi


class GetMyFace:
    """Whether the caller has a face on file."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files

    async def execute(self, user_id: UUID) -> FaceView:
        """Return the state of the user's face."""
        async with self._uow_factory() as uow:
            profile = await uow.profiles.get(user_id)
        if profile is None:
            return FaceView(False, False, None, None)
        url = await self._files.download_url(profile.photo_file_id, inline=True)
        return FaceView(True, profile.locked, profile.updated_at, url)


class UploadMyFace:
    """The caller uploads their own face."""

    def __init__(self, *, enroller: FaceEnroller, reader: GetMyFace) -> None:
        """Store the dependencies."""
        self._enroller = enroller
        self._reader = reader

    async def execute(self, user_id: UUID, data: bytes) -> FaceView:
        """Save the face; raises `FaceLockedError` when staff set it."""
        await self._enroller.enroll(
            user_id, uploaded_by=user_id, data=data, by_staff=False
        )
        return await self._reader.execute(user_id)


class DeleteMyFace:
    """The caller deletes their own face."""

    def __init__(self, *, enroller: FaceEnroller) -> None:
        """Store the dependency."""
        self._enroller = enroller

    async def execute(self, user_id: UUID) -> None:
        """Delete the face; raises `FaceLockedError` when staff set it."""
        await self._enroller.remove(user_id, by_staff=False)


class GetUserFacePhoto:
    """An administrator reads any user's face photo as a short-lived link."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files

    async def execute(self, user_id: UUID) -> FaceView:
        """Return the face with a link; raises `FaceNotFoundError` without one."""
        async with self._uow_factory() as uow:
            profile = await uow.profiles.get(user_id)
        if profile is None:
            raise FaceNotFoundError()
        url = await self._files.download_url(
            profile.photo_file_id, inline=True, ttl_seconds=300
        )
        return FaceView(True, profile.locked, profile.updated_at, url)
