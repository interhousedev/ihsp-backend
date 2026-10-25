"""Handlers of the caller's own profile photo."""

from typing import Annotated

from app.interfaces.http.dependencies import require_roles
from app.interfaces.http.v1.admin_users.photos import read_photo
from app.interfaces.http.v1.admin_users.users.schemas import UserPhotoResponse
from app.interfaces.http.v1.id.dependencies import AuthDep
from app.shared.actor import Actor, Role

from fastapi import Depends, File, UploadFile

TeacherActor = Annotated[Actor, Depends(require_roles(Role.TEACHER))]


async def put_my_photo(
    file: Annotated[UploadFile, File()], auth: AuthDep, actor: TeacherActor
) -> UserPhotoResponse:
    """Replace the caller's photo (JPEG or PNG, up to 5 MB)."""
    data = await read_photo(file)
    url = await auth.set_user_photo.execute(actor.user_id, data)
    return UserPhotoResponse(photo_url=url)


async def delete_my_photo(auth: AuthDep, actor: TeacherActor) -> UserPhotoResponse:
    """Remove the caller's photo; nothing happens when there is none."""
    await auth.remove_user_photo.execute(actor.user_id)
    return UserPhotoResponse(photo_url=None)
