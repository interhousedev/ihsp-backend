"""Tie one of the student's activities to a published catalog opportunity."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admission.tools.common import ItemId, applicant, lazy_services
from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.mcp_scopes import ADMISSION_APPLICANT_ROLES

from pydantic import Field


def register(kit: ToolKit) -> None:
    """Register the activity link tool."""
    adm = lazy_services(kit)

    @kit.tool(
        "application:write",
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("item_id", "opportunity_id")),
        roles=ADMISSION_APPLICANT_ROLES,
    )
    async def link_activity_opportunity(
        item_id: ItemId,
        opportunity_id: Annotated[
            UUID, Field(description="Id from search_opportunities.")
        ],
    ) -> dict[str, Any]:
        """Mark an activity as done through a catalog opportunity (verified link).

        Linking again replaces the previous link of that activity.
        """
        ctx = await applicant(kit)
        view = await adm.item_opportunity.link_existing(ctx, item_id, opportunity_id)
        return {
            "item_id": str(view.item_id),
            "status": view.status,
            "opportunity_id": str(view.opportunity_id),
        }
