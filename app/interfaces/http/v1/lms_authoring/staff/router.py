"""Routes that manage course staff."""

from app.interfaces.http.v1.lms_authoring.staff.handlers.add_staff import add_staff
from app.interfaces.http.v1.lms_authoring.staff.handlers.list_staff import list_staff
from app.interfaces.http.v1.lms_authoring.staff.handlers.remove_staff import (
    remove_staff,
)
from app.interfaces.http.v1.lms_authoring.staff.handlers.update_staff import (
    update_staff,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms/courses/{course_id}/staff", tags=["lms-authoring"])
router.add_api_route("", list_staff, methods=["GET"])
router.add_api_route("", add_staff, methods=["POST"])
router.add_api_route("/{user_id}", update_staff, methods=["PATCH"])
router.add_api_route("/{user_id}", remove_staff, methods=["DELETE"], status_code=204)
