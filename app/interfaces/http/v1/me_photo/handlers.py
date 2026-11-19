"""Handlers of the caller's own profile photo."""

from typing import Annotated

from app.interfaces.http.dependencies import get_actor, require_roles
from app.interfaces.http.v1.admin_users.photos import read_photo
from app.interfaces.http.v1.admin_users.users.schemas import UserPhotoResponse
from app.interfaces.http.v1.id.dependencies import AuthDep
from app.shared.actor import Actor, Role

from fastapi import Depends, File, UploadFile

TeacherActor = Annotated[Actor, Depends(require_roles(Role.TEACHER))]
AnyActor = Annotated[Actor, Depends(get_actor)]


async def put_my_photo(
    file: Annotated[UploadFile, File()], auth: AuthDep, actor: TeacherActor
) -> UserPhotoResponse:
    """Replace the teacher's photo (deprecated: use PUT /v1/me/photo)."""
    data = await read_photo(file)
    url = await auth.set_user_photo.execute(actor.user_id, data)
    return UserPhotoResponse(photo_url=url)


async def delete_my_photo(auth: AuthDep, actor: TeacherActor) -> UserPhotoResponse:
    """Remove the teacher's photo (deprecated: use DELETE /v1/me/photo)."""
    await auth.remove_user_photo.execute(actor.user_id)
    return UserPhotoResponse(photo_url=None)


async def put_my_profile_photo(
    file: Annotated[UploadFile, File()], auth: AuthDep, actor: AnyActor
) -> UserPhotoResponse:
    """Replace the caller's photo, any role (JPEG or PNG, up to 5 MB)."""
    data = await read_photo(file)
    url = await auth.set_user_photo.execute(actor.user_id, data)
    return UserPhotoResponse(photo_url=url)


async def delete_my_profile_photo(auth: AuthDep, actor: AnyActor) -> UserPhotoResponse:
    """Remove the caller's photo; nothing happens when there is none."""
    await auth.remove_user_photo.execute(actor.user_id)
    return UserPhotoResponse(photo_url=None)
