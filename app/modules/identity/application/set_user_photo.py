"""PUT /v1/admin/users/{id}/photo and /v1/staff/me/photo: set the profile photo."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.photo_files import PhotoUrls, delete_photo_file
from app.modules.identity.domain.photo import check_photo
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope


@dataclass(frozen=True, slots=True)
class SetUserPhoto:
    """Stores the image in the files module and points the user at it."""

    uow_factory: UowFactory
    files: FilesApi
    urls: PhotoUrls

    async def execute(self, user_id: UUID, data: bytes) -> str | None:
        """Validate and store the photo, replace the old one; return its link.

        The old file is deleted after the new one is committed, so a failure never
        leaves the user without a photo. Raises UserNotFoundError for an unknown user
        and a Photo*Error for an unusable image.
        """
        photo = check_photo(data)
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            stored = await self.files.store_bytes(
                owner_id=user_id,
                scope=FileScope.STAFF,
                purpose=FilePurpose.USER_PHOTO,
                name=f"photo.{photo.extension}",
                data=data,
                expires_days=None,
            )
            previous, user.photo_file_id = user.photo_file_id, stored.id
            try:
                await uow.users.save(user)
                await uow.commit()
            except Exception:  # the new file is unreachable now: remove it, re-raise
                await delete_photo_file(self.files, stored.id)
                raise
        if previous is not None:
            await delete_photo_file(self.files, previous)
        return await self.urls.url(stored.id)
