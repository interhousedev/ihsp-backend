"""Legal routes: public documents, the user's consent, administrators' editor."""

from app.interfaces.http.v1.legal.handlers import admin, documents, me
from app.interfaces.http.v1.legal.schemas import (
    AcceptanceCountsOut,
    AdminDocumentListOut,
    AdminDocumentOut,
    LegalDocumentListOut,
    LegalDocumentOut,
    OverviewOut,
    PendingOut,
)

from fastapi import APIRouter

public = APIRouter(prefix="/v1/legal", tags=["legal"])
public.add_api_route(
    "/documents",
    documents.list_documents,
    methods=["GET"],
    response_model=LegalDocumentListOut,
)
public.add_api_route(
    "/documents/{kind}",
    documents.get_document,
    methods=["GET"],
    response_model=LegalDocumentOut,
)

mine = APIRouter(prefix="/v1/me/legal", tags=["legal"])
mine.add_api_route(
    "/pending", me.get_pending, methods=["GET"], response_model=PendingOut
)
mine.add_api_route("/accept", me.accept, methods=["POST"], response_model=PendingOut)

admin_router = APIRouter(prefix="/v1/admin/legal", tags=["admin-legal"])
admin_router.add_api_route(
    "/documents",
    admin.list_all,
    methods=["GET"],
    response_model=AdminDocumentListOut,
)
admin_router.add_api_route(
    "/overview", admin.overview, methods=["GET"], response_model=OverviewOut
)
admin_router.add_api_route(
    "/drafts/{kind}",
    admin.save_draft,
    methods=["PUT"],
    response_model=AdminDocumentOut,
)
admin_router.add_api_route(
    "/drafts/{kind}/publish",
    admin.publish,
    methods=["POST"],
    response_model=AdminDocumentOut,
)
admin_router.add_api_route(
    "/acceptances",
    admin.acceptance_counts,
    methods=["GET"],
    response_model=AcceptanceCountsOut,
)
