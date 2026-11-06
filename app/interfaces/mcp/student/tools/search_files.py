"""Students tool `search_files`."""

from typing import Annotated, Any

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import SEARCH_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "files:read"
WIDE_SCOPE = "files:read.all"
UNTRUSTED = ("results[].name", "results[].snippet")


def _summary(result: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"count": len(result.get("results", []))}


def register(kit: ToolKit) -> None:
    """Register `search_files`."""

    @kit.tool(
        SCOPE,
        limit=SEARCH_LIMIT,
        log=LogSpec(keep=("limit", "only_personal"), summarize=_summary),
    )
    async def search_files(
        query: Annotated[
            str, Field(min_length=1, max_length=200, description="Words to look for.")
        ],
        limit: Annotated[int, Field(ge=1, le=20, description="Most results.")] = 10,
        only_personal: Annotated[
            bool, Field(description="Search only personal uploaded files.")
        ] = False,
    ) -> dict[str, Any]:
        """Search the text of files the student may read; returns ids with snippets.

        By default every file list_files can show (needs `files:read.all`; otherwise,
        or with only_personal, own uploads only). `truncated` means only the newest
        files were searched.
        """
        actor = current_actor()
        wide = await kit.guard.has_scope(actor, WIDE_SCOPE)
        if only_personal or not wide:
            results = await kit.deps.files.search_text(actor.user_id, query, limit)
            return mark_untrusted(
                {"results": results, "scope_limited": not only_personal and not wide},
                *UNTRUSTED,
            )
        found = await kit.deps.files_courses_tools.search_visible_files(
            actor, query, only_personal=False, limit=limit
        )
        return mark_untrusted({**found, "scope_limited": False}, *UNTRUSTED)
