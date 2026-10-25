"""Routes of the default materials of subjects (admin, by EMIS subject id)."""

from app.interfaces.http.v1.notebooks.handlers import (
    add_default_material,
    list_default_materials,
    reconcile_subject_materials,
    remove_default_material,
)
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    ReconcileJobAccepted,
    ReconcileJobStatus,
    SubjectMaterialGroupResponse,
    SubjectMaterialResponse,
)

from fastapi import APIRouter, status

router = APIRouter(
    prefix="/v1/admin/subject-materials", tags=["admin-subject-materials"]
)

router.add_api_route(
    "",
    list_default_materials.list_all_default_materials,
    methods=["GET"],
    response_model=list[SubjectMaterialGroupResponse],
)
router.add_api_route(
    "/{edu_subject_id}",
    list_default_materials.list_default_materials,
    methods=["GET"],
    response_model=list[SubjectMaterialResponse],
)
router.add_api_route(
    "/{edu_subject_id}",
    add_default_material.add_default_material,
    methods=["POST"],
    response_model=SubjectMaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/{edu_subject_id}/{material_id}",
    remove_default_material.remove_default_material,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/subjects/{subject_id}/reconcile",
    reconcile_subject_materials.reconcile_admin_subject_materials,
    methods=["POST"],
    response_model=ReconcileJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(
    "/subjects/{subject_id}/reconcile/{job_id}",
    reconcile_subject_materials.get_admin_reconcile_status,
    methods=["GET"],
    response_model=ReconcileJobStatus,
)
