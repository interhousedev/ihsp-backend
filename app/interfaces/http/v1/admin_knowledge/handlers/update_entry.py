"""PATCH /v1/admin/knowledge/{entry_id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_knowledge.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_knowledge.schemas import (
    KnowledgeEntryPatch,
    KnowledgeEntryResponse,
)


async def update_entry(
    entry_id: UUID,
    body: KnowledgeEntryPatch,
    container: ContainerDep,
    actor: AdminActor,
) -> KnowledgeEntryResponse:
    """Change the sent fields; the entry is embedded again."""
    changes = body.model_dump(exclude_unset=True)
    if changes.get("key") is None:
        changes.pop("key", None)
    if changes.get("value") is None:
        changes.pop("value", None)
    for flag in ("accessible_to_guest", "accessible_to_student"):
        if changes.get(flag) is None:
            changes.pop(flag, None)
    entry = await container.knowledge.update_entry.execute(entry_id, changes)
    return KnowledgeEntryResponse.from_domain(entry)
