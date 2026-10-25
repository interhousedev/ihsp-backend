"""DELETE /v1/admin/users/{id}/photo and /v1/staff/me/photo: remove the photo."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.photo_files import delete_photo_file
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FilesApi


@dataclass(frozen=True, slots=True)
class RemoveUserPhoto:
    """Clears the link first, then deletes the file."""

    uow_factory: UowFactory
    files: FilesApi

    async def execute(self, user_id: UUID) -> None:
        """Remove the photo; repeating the call is fine.

        Raises UserNotFoundError for an unknown user.
        """
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            previous = user.photo_file_id
            if previous is None:
                return
            user.photo_file_id = None
            await uow.users.save(user)
            await uow.commit()
        await delete_photo_file(self.files, previous)
