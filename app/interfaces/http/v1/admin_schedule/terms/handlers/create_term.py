"""POST /v1/admin/terms."""

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.terms.schemas import (
    TermInputBody,
    TermResponse,
)


async def create_term(
    body: TermInputBody, container: ContainerDep, actor: AdminActor
) -> TermResponse:
    """Create a term."""
    term = await container.academic.schedule.create_term.execute(
        academic_year=body.academic_year,
        half=body.half,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        bells=body.bells,
        non_study_days=body.non_study_days,
        moved_days=body.moved_days,
        control_periods=body.control_periods,
    )
    return TermResponse.model_validate(term)
