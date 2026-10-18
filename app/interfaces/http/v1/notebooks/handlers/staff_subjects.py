"""Routes of a teacher's subjects and the materials they keep for them."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.notebooks.deps import Notebooks, TeacherActor
from app.interfaces.http.v1.notebooks.reconcile_jobs import (
    reconcile_status,
    start_reconcile,
)
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    ReconcileJobAccepted,
    ReconcileJobStatus,
    SubjectMaterialResponse,
)
from app.interfaces.http.v1.notebooks.schemas_staff_subjects import (
    StaffSubjectMaterialCreateBody,
    StaffSubjectMaterialsResponse,
    StaffSubjectResponse,
)
from app.modules.notebooks.application.material_target import DefaultMaterialDraft

from fastapi import Depends, Response, status


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


async def reconcile_staff_subject_materials(
    subject_id: UUID,
    notebooks: Notebooks,
    actor: TeacherActor,
    container: Annotated[Container, Depends(get_container)],
) -> ReconcileJobAccepted:
    """Queue the sync of the teacher's own subject notebooks; answer 202."""
    return await start_reconcile(container, subject_id, actor.user_id, actor.user_id)


async def get_staff_reconcile_status(
    subject_id: UUID,
    job_id: str,
    notebooks: Notebooks,
    actor: TeacherActor,
    container: Annotated[Container, Depends(get_container)],
) -> ReconcileJobStatus:
    """The totals of a reconcile job the teacher started."""
    return await reconcile_status(container, job_id, started_by=actor.user_id)
