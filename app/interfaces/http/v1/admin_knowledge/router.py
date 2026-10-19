"""Routes of the knowledge base (`/v1/admin/knowledge/*`, administrators only)."""

from app.interfaces.http.v1.admin_knowledge.handlers import (
    create_entry,
    delete_entry,
    get_entry,
    list_entries,
    update_entry,
)
from app.interfaces.http.v1.admin_knowledge.schemas import (
    KnowledgeEntryListResponse,
    KnowledgeEntryResponse,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/admin/knowledge", tags=["admin-knowledge"])

router.add_api_route(
    "",
    list_entries.list_entries,
    methods=["GET"],
    response_model=KnowledgeEntryListResponse,
)
router.add_api_route(
    "",
    create_entry.create_entry,
    methods=["POST"],
    response_model=KnowledgeEntryResponse,
)
router.add_api_route(
    "/{entry_id}",
    get_entry.get_entry,
    methods=["GET"],
    response_model=KnowledgeEntryResponse,
)
router.add_api_route(
    "/{entry_id}",
    update_entry.update_entry,
    methods=["PATCH"],
    response_model=KnowledgeEntryResponse,
)
router.add_api_route(
    "/{entry_id}",
    delete_entry.delete_entry,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
