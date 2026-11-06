"""Students tool `refresh_my_marks`."""

from typing import Any

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "sync:run"


def register(kit: ToolKit) -> None:
    """Register `refresh_my_marks`."""

    @kit.tool(
        SCOPE,
        read_only=False,
        log=LogSpec(summarize=lambda r: {"status": r["status"]}),
    )
    async def refresh_my_marks() -> dict[str, Any]:
        """Ask EMIS for the student's latest marks, timetable and teachers.

        At most once per 30 minutes. `status` is queued (started), running (a sync is
        already under way; this call cost nothing) or cooldown (try again after
        `retry_after_seconds`). The work runs in the background and can take minutes:
        read get_sync_status later rather than calling this again.
        """
        actor = current_actor()
        result = await kit.deps.academic_tools.request_refresh(actor)
        return {**result, "links": kit.deps.web_links.settings()}
