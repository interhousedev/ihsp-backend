"""GET /v1/admin/knowledge/{entry_id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_knowledge.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_knowledge.schemas import KnowledgeEntryResponse


async def get_entry(
    entry_id: UUID, container: ContainerDep, actor: AdminActor
) -> KnowledgeEntryResponse:
    """Return one entry."""
    entry = await container.knowledge.get_entry.execute(entry_id)
    return KnowledgeEntryResponse.from_domain(entry)
