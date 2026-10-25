"""POST /v1/admin/subjects/{id}/emis-pull."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.subjects.schemas import EmisPullBody
from app.shared.jobs import RedisJobTracker, enqueue

from fastapi import Response


async def emis_pull(
    subject_id: UUID, body: EmisPullBody, container: ContainerDep, actor: AdminActor
) -> Response:
    """Pull the subject's EMIS materials in the worker (full or soft); answers 202."""
    title = await container.academic.schedule.queries.subject_title(subject_id)
    label = f"EMIS {body.mode} pull: {title or subject_id}"
    if body.teacher_id is not None:
        label += f", teacher {body.teacher_id}"
    if body.group_id is not None:
        label += f", group {body.group_id}"
    job_id = await enqueue(
        RedisJobTracker(container.redis),
        "subject_materials_pull",
        label,
        started_by=str(actor.user_id),
    )
    await container.academic.marks.run_manual_sync.pull_subject(
        actor,
        subject_id,
        mode=body.mode,
        teacher_id=body.teacher_id,
        group_id=body.group_id,
        terms=(
            None
            if body.terms is None
            else [(term.academic_year, term.half) for term in body.terms]
        ),
        job_id=job_id,
    )
    return Response(status_code=202)
