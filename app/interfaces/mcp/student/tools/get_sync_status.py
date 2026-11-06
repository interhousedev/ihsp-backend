"""Students tool `get_sync_status`."""

from typing import Any

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "sync:run"


def register(kit: ToolKit) -> None:
    """Register `get_sync_status`."""

    @kit.tool(SCOPE, log=LogSpec(summarize=lambda r: {"status": r["status"]}))
    async def get_sync_status() -> dict[str, Any]:
        """Show the student's EMIS sync: status, times and marks synced.

        `status` is never, pending, running, succeeded or failed. `job.error` is a
        code: emis_reauth_required (the student must sign in to EMIS again; see
        links.open), emis_unavailable, stopped or sync_failed.
        """
        actor = current_actor()
        result = await kit.deps.academic_tools.sync_status(actor.user_id)
        return {**result, "links": kit.deps.web_links.settings()}
