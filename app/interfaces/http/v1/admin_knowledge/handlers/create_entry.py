"""POST /v1/admin/knowledge."""

from app.interfaces.http.v1.admin_knowledge.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_knowledge.schemas import (
    KnowledgeEntryInput,
    KnowledgeEntryResponse,
)


async def create_entry(
    body: KnowledgeEntryInput, container: ContainerDep, actor: AdminActor
) -> KnowledgeEntryResponse:
    """Create an entry; a key that exists (any case) answers 409."""
    entry = await container.knowledge.create_entry.execute(
        actor.user_id,
        key=body.key,
        value=body.value,
        title=body.title,
        tags=body.tags,
        accessible_to_guest=body.accessible_to_guest,
        accessible_to_student=body.accessible_to_student,
    )
    return KnowledgeEntryResponse.from_domain(entry)
