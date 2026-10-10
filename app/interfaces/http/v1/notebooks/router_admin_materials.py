"""Routes of the default materials of subjects (admin, by EMIS subject id)."""

from app.interfaces.http.v1.notebooks.handlers import (
    add_default_material,
    list_default_materials,
    remove_default_material,
)
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
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
