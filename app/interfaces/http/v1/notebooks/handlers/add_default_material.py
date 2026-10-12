"""POST /v1/admin/subject-materials/{edu_subject_id}."""

from typing import Annotated

from app.interfaces.http.v1.notebooks.deps import AdminActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    SubjectMaterialCreateBody,
    SubjectMaterialResponse,
)
from app.modules.notebooks.application.material_target import DefaultMaterialDraft

from fastapi import Path


async def add_default_material(
    edu_subject_id: Annotated[int, Path(ge=1)],
    body: SubjectMaterialCreateBody,
    notebooks: Notebooks,
    actor: AdminActor,
) -> SubjectMaterialResponse:
    """Add a file, link or library item every student's subject notebook gets."""
    material = await notebooks.add_default_material.execute(
        actor,
        edu_subject_id,
        DefaultMaterialDraft(
            kind=body.kind,
            title=body.title,
            url=body.url,
            file_id=body.file_id,
            library_item_id=body.library_item_id,
        ),
    )
    return SubjectMaterialResponse.from_entity(material)
