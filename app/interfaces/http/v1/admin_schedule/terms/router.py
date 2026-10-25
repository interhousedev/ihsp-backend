"""Router of /v1/admin/terms."""

from app.interfaces.http.v1.admin_schedule.terms.handlers.create_term import (
    create_term,
)
from app.interfaces.http.v1.admin_schedule.terms.handlers.list_terms import list_terms
from app.interfaces.http.v1.admin_schedule.terms.handlers.update_term import (
    update_term,
)
from app.interfaces.http.v1.admin_schedule.terms.schemas import TermResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/terms", tags=["admin-schedule"])
router.add_api_route("", list_terms, methods=["GET"], response_model=list[TermResponse])
router.add_api_route("", create_term, methods=["POST"], response_model=TermResponse)
router.add_api_route(
    "/{term_id}", update_term, methods=["PATCH"], response_model=TermResponse
)
