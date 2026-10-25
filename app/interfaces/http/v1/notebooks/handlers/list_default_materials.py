"""GET /v1/admin/subject-materials and .../subject-materials/{edu_subject_id}."""

from typing import Annotated

from app.interfaces.http.v1.notebooks.deps import AdminActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    SubjectMaterialGroupResponse,
    SubjectMaterialResponse,
)

from fastapi import Path


async def list_all_default_materials(
    notebooks: Notebooks, actor: AdminActor
) -> list[SubjectMaterialGroupResponse]:
    """The default materials of every EMIS subject id, grouped, by id."""
    materials = await notebooks.list_default_materials.execute()
    groups: dict[int, list[SubjectMaterialResponse]] = {}
    for material in materials:
        groups.setdefault(material.edu_subject_id, []).append(
            SubjectMaterialResponse.from_entity(material)
        )
    return [
        SubjectMaterialGroupResponse(edu_subject_id=edu_id, materials=items)
        for edu_id, items in groups.items()
    ]


async def list_default_materials(
    edu_subject_id: Annotated[int, Path(ge=1)],
    notebooks: Notebooks,
    actor: AdminActor,
) -> list[SubjectMaterialResponse]:
    """The default materials of one EMIS subject id, in their order."""
    materials = await notebooks.list_default_materials.execute(edu_subject_id)
    return [SubjectMaterialResponse.from_entity(material) for material in materials]
