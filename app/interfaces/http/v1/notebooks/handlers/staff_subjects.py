"""Routes of a teacher's subjects and the materials they keep for them."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import Notebooks, TeacherActor
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    SubjectMaterialResponse,
)
from app.interfaces.http.v1.notebooks.schemas_staff_subjects import (
    StaffSubjectMaterialCreateBody,
    StaffSubjectMaterialsResponse,
    StaffSubjectResponse,
)
from app.modules.notebooks.application.material_target import DefaultMaterialDraft

from fastapi import Response, status


async def list_staff_subjects(
    notebooks: Notebooks, actor: TeacherActor
) -> list[StaffSubjectResponse]:
    """The subjects the teacher teaches this term, each with its groups."""
    subjects = await notebooks.staff_subject_materials.subjects(actor)
    return [StaffSubjectResponse.from_subject(x) for x in subjects]


async def get_staff_subject_materials(
    subject_id: UUID, notebooks: Notebooks, actor: TeacherActor
) -> StaffSubjectMaterialsResponse:
    """The administration (read-only), own and per-group materials of a subject."""
    view = await notebooks.staff_subject_materials.overview(actor, subject_id)
    return StaffSubjectMaterialsResponse.from_view(view)


async def add_staff_subject_material(
    subject_id: UUID,
    body: StaffSubjectMaterialCreateBody,
    notebooks: Notebooks,
    actor: TeacherActor,
) -> SubjectMaterialResponse:
    """Add a material for all the teacher's groups, or for one group (`group_id`)."""
    material = await notebooks.staff_subject_materials.add(
        actor,
        subject_id,
        DefaultMaterialDraft(
            kind=body.kind,
            title=body.title,
            url=body.url,
            file_id=body.file_id,
            library_item_id=body.library_item_id,
        ),
        group_id=body.group_id,
        subgroup=body.subgroup,
    )
    return SubjectMaterialResponse.from_entity(material)


async def remove_staff_subject_material(
    subject_id: UUID, material_id: UUID, notebooks: Notebooks, actor: TeacherActor
) -> Response:
    """Remove one of the teacher's own materials; notebooks follow on their sync."""
    await notebooks.staff_subject_materials.remove(actor, subject_id, material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
