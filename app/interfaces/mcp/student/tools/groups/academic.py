"""Students tools of sync, teachers, GPA and lesson detail."""

from types import ModuleType

from app.interfaces.mcp.student.tools import (
    get_gpa,
    get_lesson_detail,
    get_my_teachers,
    get_sync_status,
    get_teacher_timetable,
    refresh_my_marks,
)

TOOL_MODULES: tuple[ModuleType, ...] = (
    refresh_my_marks,
    get_sync_status,
    get_my_teachers,
    get_teacher_timetable,
    get_gpa,
    get_lesson_detail,
)
