"""Routes under ``/v1/staff``: the temporary gradebook (TMP-1, TMP-3)."""

from app.interfaces.http.v1.staff_temporary_marks.handlers.delete_temporary_mark import (  # noqa: E501
    delete_temporary_mark,
)
from app.interfaces.http.v1.staff_temporary_marks.handlers.list_lesson_temporary_marks import (  # noqa: E501
    list_lesson_temporary_marks,
)
from app.interfaces.http.v1.staff_temporary_marks.handlers.list_pending_temporary_marks import (  # noqa: E501
    list_pending_temporary_marks,
)
from app.interfaces.http.v1.staff_temporary_marks.handlers.set_temporary_mark import (
    set_temporary_mark,
)

from fastapi import APIRouter

MARK = "/lessons/{id}/temporary-marks/{student_id}"

router = APIRouter(prefix="/v1/staff", tags=["staff-temporary-marks"])
router.add_api_route(
    "/lessons/{id}/temporary-marks", list_lesson_temporary_marks, methods=["GET"]
)
router.add_api_route(MARK, set_temporary_mark, methods=["PUT"])
router.add_api_route(MARK, delete_temporary_mark, methods=["DELETE"], status_code=204)
router.add_api_route(
    "/temporary-marks/pending", list_pending_temporary_marks, methods=["GET"]
)
