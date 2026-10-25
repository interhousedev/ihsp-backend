"""Routes /v1/staff/me/photo."""

from app.interfaces.http.v1.admin_users.users.schemas import UserPhotoResponse
from app.interfaces.http.v1.me_photo.handlers import delete_my_photo, put_my_photo

from fastapi import APIRouter

router = APIRouter(tags=["photo"])
router.add_api_route(
    "/v1/staff/me/photo",
    put_my_photo,
    methods=["PUT"],
    response_model=UserPhotoResponse,
)
router.add_api_route(
    "/v1/staff/me/photo",
    delete_my_photo,
    methods=["DELETE"],
    response_model=UserPhotoResponse,
)
