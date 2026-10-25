"""Router of /v1/admin/timetable."""

from app.interfaces.http.v1.admin_schedule.timetable.handlers.check_entry import (
    check_entry,
)
from app.interfaces.http.v1.admin_schedule.timetable.handlers.copy_timetable import (
    copy_timetable,
)
from app.interfaces.http.v1.admin_schedule.timetable.handlers.create_entry import (
    create_entry,
)
from app.interfaces.http.v1.admin_schedule.timetable.handlers.delete_entry import (
    delete_entry,
)
from app.interfaces.http.v1.admin_schedule.timetable.handlers.list_entries import (
    list_entries,
)
from app.interfaces.http.v1.admin_schedule.timetable.handlers.update_entry import (
    update_entry,
)
from app.interfaces.http.v1.admin_schedule.timetable.schemas import (
    CheckResponse,
    CopyResponse,
    TimetableEntryResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/timetable", tags=["admin-schedule"])
router.add_api_route(
    "", list_entries, methods=["GET"], response_model=list[TimetableEntryResponse]
)
router.add_api_route(
    "", create_entry, methods=["POST"], response_model=TimetableEntryResponse
)
router.add_api_route(
    "/check", check_entry, methods=["POST"], response_model=CheckResponse
)
router.add_api_route(
    "/copy", copy_timetable, methods=["POST"], response_model=CopyResponse
)
router.add_api_route(
    "/{entry_id}",
    update_entry,
    methods=["PATCH"],
    response_model=TimetableEntryResponse,
)
router.add_api_route("/{entry_id}", delete_entry, methods=["DELETE"], status_code=204)
