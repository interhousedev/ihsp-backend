"""PATCH /v1/admin/terms/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.terms.schemas import (
    TermPatchBody,
    TermResponse,
)


async def update_term(
    term_id: UUID, body: TermPatchBody, container: ContainerDep, actor: AdminActor
) -> TermResponse:
    """Change the fields that were sent."""
    term = await container.academic.schedule.update_term.execute(
        term_id,
        academic_year=body.academic_year,
        half=body.half,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        bells=body.bells,
        non_study_days=body.non_study_days,
        moved_days=body.moved_days,
    )
    return TermResponse.model_validate(term)
