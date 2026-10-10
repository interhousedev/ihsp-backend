"""PUT /v1/admin/users/{id}/photo."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admin_users.photos import read_photo
from app.interfaces.http.v1.admin_users.users.schemas import UserPhotoResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep

from fastapi import File, UploadFile


async def put_photo(
    id: UUID,
    file: Annotated[UploadFile, File()],
    _admin: AdminDep,
    auth: AuthDep,
) -> UserPhotoResponse:
    """Replace the user's photo (JPEG or PNG, up to 5 MB)."""
    data = await read_photo(file)
    return UserPhotoResponse(photo_url=await auth.set_user_photo.execute(id, data))
