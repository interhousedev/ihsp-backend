"""DELETE /v1/admin/users/{id}/photo."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.users.schemas import UserPhotoResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep


async def delete_photo(id: UUID, _admin: AdminDep, auth: AuthDep) -> UserPhotoResponse:
    """Remove the user's photo; nothing happens when there is none."""
    await auth.remove_user_photo.execute(id)
    return UserPhotoResponse(photo_url=None)
