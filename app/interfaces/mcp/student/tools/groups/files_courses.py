"""Students tools of enrolled course content and media links."""

from types import ModuleType

from app.interfaces.mcp.student.tools import (
    get_course_curriculum,
    get_course_media_link,
    get_course_step,
    list_my_courses,
)

TOOL_MODULES: tuple[ModuleType, ...] = (
    list_my_courses,
    get_course_curriculum,
    get_course_step,
    get_course_media_link,
)
