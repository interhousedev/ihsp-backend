"""Routes under ``/v1/staff``: work-off templates and work-offs."""

from app.interfaces.http.v1.staff_work_offs.handlers.create_work_off_template import (
    create_work_off_template,
)
from app.interfaces.http.v1.staff_work_offs.handlers.delete_work_off import (
    delete_work_off,
)
from app.interfaces.http.v1.staff_work_offs.handlers.delete_work_off_template import (
    delete_work_off_template,
)
from app.interfaces.http.v1.staff_work_offs.handlers.list_work_off_templates import (
    list_work_off_templates,
)
from app.interfaces.http.v1.staff_work_offs.handlers.update_work_off import (
    update_work_off,
)
from app.interfaces.http.v1.staff_work_offs.handlers.update_work_off_template import (
    update_work_off_template,
)
from app.interfaces.http.v1.staff_work_offs.schemas import (
    WorkOffTemplateResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/staff", tags=["staff-work-offs"])
router.add_api_route("/work-off-templates", list_work_off_templates, methods=["GET"])
router.add_api_route(
    "/work-off-templates",
    create_work_off_template,
    methods=["POST"],
    status_code=201,
    response_model=WorkOffTemplateResponse,
)
router.add_api_route(
    "/work-off-templates/{id}", update_work_off_template, methods=["PUT"]
)
router.add_api_route(
    "/work-off-templates/{id}",
    delete_work_off_template,
    methods=["DELETE"],
    status_code=204,
)
router.add_api_route("/work-offs/{id}", update_work_off, methods=["PATCH"])
router.add_api_route(
    "/work-offs/{id}", delete_work_off, methods=["DELETE"], status_code=204
)
