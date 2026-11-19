"""Handlers of the caller's own profile photo."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container, require_roles
from app.interfaces.http.v1.admin_users.photos import read_photo
from app.interfaces.http.v1.admin_users.users.schemas import (
    MePhotoResponse,
    UserPhotoResponse,
)
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
) -> MePhotoResponse:
    """Replace the caller's photo, any role (JPEG or PNG, up to 5 MB)."""
    data = await read_photo(file)
    url = await auth.set_user_photo.execute(actor.user_id, data)
    return MePhotoResponse(photo_url=url, photo_source="upload")


async def delete_my_profile_photo(
    auth: AuthDep,
    actor: AnyActor,
    container: Annotated[Container, Depends(get_container)],
) -> MePhotoResponse:
    """Remove the uploaded photo; the entrance face photo, if any, takes its place."""
    await auth.remove_user_photo.execute(actor.user_id)
    await container.faces.restore_profile_photo.execute(actor.user_id)
    me = await auth.get_me.execute(actor)
    return MePhotoResponse(photo_url=me.photo_url, photo_source=me.photo_source)
