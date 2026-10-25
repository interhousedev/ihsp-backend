"""AdminToolBackend: maps every Administration tool name to a module use case."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.bootstrap.adapters import admin_tools_read as read
from app.bootstrap.adapters import admin_tools_write as write
from app.bootstrap.container import Container
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError

ToolHandler = Callable[[Container, Mapping[str, Any], Actor], Awaitable[dict[str, Any]]]

READ_TOOLS: dict[str, ToolHandler] = {
    "search_users": read.search_users,
    "get_student": read.get_student,
    "list_teachers": read.list_teachers,
    "list_groups": read.list_groups,
    "get_group": read.get_group,
    "get_timetable": read.get_timetable,
    "list_lessons": read.list_lessons,
    "attendance_stats": read.attendance_stats,
    "missing_attendance": read.missing_attendance,
    "list_broadcasts": read.list_broadcasts,
    "sync_status": read.sync_status,
    "audit_log": read.audit_log,
}

WRITE_TOOLS: dict[str, ToolHandler] = {
    "create_teacher": write.create_teacher,
    "update_teacher": write.update_teacher,
    "create_group": write.create_group,
    "update_group": write.update_group,
    "create_timetable_entry": write.create_timetable_entry,
    "update_timetable_entry": write.update_timetable_entry,
    "delete_timetable_entry": write.delete_timetable_entry,
    "create_lesson": write.create_lesson,
    "update_lesson": write.update_lesson,
    "create_broadcast_draft": write.create_broadcast_draft,
}


class AdminToolBackendAdapter:
    """Backend of the Administration assistant and the MCP admin server.

    The assistant (write tools after approval) and the MCP admin server (read
    tools) call the backend only through this object. Arguments are the JSON the
    model or client sent; both the AI names (`from`, `to`) and the MCP names
    (`date_from`, `date_to`) are accepted. The use cases check the actor's rights
    themselves.
    """

    def __init__(self, container: Container) -> None:
        """Keep the container; use cases are looked up per call (built later)."""
        self._container = container
        self._tools: dict[str, ToolHandler] = {**READ_TOOLS, **WRITE_TOOLS}

    async def call(
        self, tool: str, arguments: dict[str, Any], actor: Actor
    ) -> dict[str, Any]:
        """Run an Administration tool as the actor."""
        handler = self._tools.get(tool)
        if handler is None:
            raise NotFoundError(params={"tool": tool}, support_details=f"tool {tool}")
        return await handler(self._container, arguments, actor)
