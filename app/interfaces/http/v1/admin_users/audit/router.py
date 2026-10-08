"""Route /v1/admin/audit."""

from app.interfaces.http.v1.admin_users.audit.handlers.get_audit import get_audit
from app.interfaces.http.v1.id.schemas import AuditItemResponse
from app.shared.pagination import Page

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/audit", tags=["admin-audit"])

router.add_api_route(
    "", get_audit, methods=["GET"], response_model=Page[AuditItemResponse]
)
