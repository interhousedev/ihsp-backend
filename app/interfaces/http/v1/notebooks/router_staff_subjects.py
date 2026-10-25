"""Routes of a teacher's subjects and their materials (`/v1/staff/subjects`)."""

from app.interfaces.http.v1.notebooks.handlers import staff_subjects
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    ReconcileJobAccepted,
    ReconcileJobStatus,
    SubjectMaterialResponse,
)
from app.interfaces.http.v1.notebooks.schemas_staff_subjects import (
    StaffSubjectMaterialsResponse,
    StaffSubjectResponse,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/staff/subjects", tags=["staff-subjects"])

router.add_api_route(
    "",
    staff_subjects.list_staff_subjects,
    methods=["GET"],
    response_model=list[StaffSubjectResponse],
)
router.add_api_route(
    "/{subject_id}/materials",
    staff_subjects.get_staff_subject_materials,
    methods=["GET"],
    response_model=StaffSubjectMaterialsResponse,
)
router.add_api_route(
    "/{subject_id}/materials",
    staff_subjects.add_staff_subject_material,
    methods=["POST"],
    response_model=SubjectMaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/{subject_id}/materials/{material_id}",
    staff_subjects.remove_staff_subject_material,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/{subject_id}/reconcile",
    staff_subjects.reconcile_staff_subject_materials,
    methods=["POST"],
    response_model=ReconcileJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(
    "/{subject_id}/reconcile/{job_id}",
    staff_subjects.get_staff_reconcile_status,
    methods=["GET"],
    response_model=ReconcileJobStatus,
)
