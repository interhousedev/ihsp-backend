"""Routes to browse, compare and restore versions."""

from app.interfaces.http.v1.lms_authoring.versions.handlers.compare_versions import (
    compare_versions,
)
from app.interfaces.http.v1.lms_authoring.versions.handlers.get_version import (
    get_version,
)
from app.interfaces.http.v1.lms_authoring.versions.handlers.list_versions import (
    list_versions,
)
from app.interfaces.http.v1.lms_authoring.versions.handlers.restore_version import (
    restore_version,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms/courses/{course_id}", tags=["lms-authoring"])
router.add_api_route("/versions", list_versions, methods=["GET"])
router.add_api_route("/versions/{number}", get_version, methods=["GET"])
router.add_api_route("/compare", compare_versions, methods=["GET"])
router.add_api_route("/versions/{number}/restore", restore_version, methods=["POST"])
