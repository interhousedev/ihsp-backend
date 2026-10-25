"""GET /v1/admin/terms."""

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.terms.schemas import TermResponse


async def list_terms(container: ContainerDep, actor: AdminActor) -> list[TermResponse]:
    """Return all terms with the current one flagged."""
    terms = await container.academic.schedule.list_terms.execute()
    return [TermResponse.model_validate(term) for term in terms]
