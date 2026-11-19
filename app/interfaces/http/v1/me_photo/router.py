"""Routes /v1/me/photo (every role) and the deprecated /v1/staff/me/photo."""

from app.interfaces.http.v1.admin_users.users.schemas import (
    MePhotoResponse,
    UserPhotoResponse,
)
from app.interfaces.http.v1.me_photo.handlers import (
    delete_my_photo,
    delete_my_profile_photo,
    put_my_photo,
    put_my_profile_photo,
)

from fastapi import APIRouter

router = APIRouter(tags=["photo"])
router.add_api_route(
    "/v1/me/photo",
    put_my_profile_photo,
    methods=["PUT"],
    response_model=MePhotoResponse,
    operation_id="me_put_photo",
    responses={
        401: {"description": "Not signed in."},
        404: {"description": "The account no longer exists."},
        413: {"description": "The photo is larger than 5 MB."},
        422: {"description": "The photo is empty, not JPEG or PNG, or unreadable."},
    },
)
router.add_api_route(
    "/v1/me/photo",
    delete_my_profile_photo,
    methods=["DELETE"],
    response_model=MePhotoResponse,
    operation_id="me_delete_photo",
    responses={401: {"description": "Not signed in."}},
)
router.add_api_route(
    "/v1/staff/me/photo",
    put_my_photo,
    methods=["PUT"],
    response_model=UserPhotoResponse,
    deprecated=True,
)
router.add_api_route(
    "/v1/staff/me/photo",
    delete_my_photo,
    methods=["DELETE"],
    response_model=UserPhotoResponse,
    deprecated=True,
)
