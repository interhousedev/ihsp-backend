"""Students tool `get_my_group`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

SCOPE = "group:read"


def register(kit: ToolKit) -> None:
    """Register `get_my_group`."""

    @kit.tool(SCOPE)
    async def get_my_group() -> dict[str, Any]:
        """Show the student's own group: homeroom teacher, head student and members.

        Members are the active students of the group, sorted by name; `is_me` marks
        the student. `homeroom_teacher` carries the public contacts the teacher chose
        to show. Unassigned roles are null. Photos are never included.
        """
        actor = current_actor()
        group = await kit.deps.academic_tools.my_group(actor)
        return mark_untrusted(
            group,
            "name",
            "homeroom_teacher.first_name",
            "homeroom_teacher.last_name",
            "head_student.first_name",
            "head_student.last_name",
            "members[].first_name",
            "members[].last_name",
            "homeroom_teacher.contacts.office_hours",
            "homeroom_teacher.contacts.office",
            "homeroom_teacher.contacts.note",
        )
