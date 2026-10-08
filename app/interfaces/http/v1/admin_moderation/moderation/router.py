"""Routes of the moderation queue (ADM-13)."""

from app.interfaces.http.v1.admin_moderation.moderation.handlers import (
    dismiss_reports as dismiss_module,
)
from app.interfaces.http.v1.admin_moderation.moderation.handlers.disable_link import (
    disable_link,
)
from app.interfaces.http.v1.admin_moderation.moderation.handlers.queue import queue
from app.interfaces.http.v1.admin_moderation.moderation.handlers.search import search
from app.interfaces.http.v1.admin_moderation.moderation.schemas import (
    ModerationPageResponse,
)
from app.interfaces.http.v1.links.schemas import ModerationItem

from fastapi import APIRouter

router = APIRouter(tags=["admin"])
router.add_api_route(
    "/v1/admin/moderation/queue",
    queue,
    methods=["GET"],
    response_model=ModerationPageResponse,
)
router.add_api_route(
    "/v1/admin/moderation/search",
    search,
    methods=["GET"],
    response_model=list[ModerationItem],
)
router.add_api_route(
    "/v1/admin/links/{link_id}/disable",
    disable_link,
    methods=["POST"],
    response_model=ModerationItem,
)
router.add_api_route(
    "/v1/admin/links/{link_id}/dismiss-reports",
    dismiss_module.dismiss_reports,
    methods=["POST"],
    response_model=ModerationItem,
)
