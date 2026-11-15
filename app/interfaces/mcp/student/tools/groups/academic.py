"""Students tools of sync, teachers, GPA, lesson detail, group and notifications."""

from types import ModuleType

from app.interfaces.mcp import list_notifications
from app.interfaces.mcp.student.tools import (
    get_gpa,
    get_lesson_detail,
    get_my_group,
    get_my_teachers,
    get_rating_book,
    get_sync_status,
    get_teacher_timetable,
    refresh_my_marks,
    submit_homework,
)

TOOL_MODULES: tuple[ModuleType, ...] = (
    refresh_my_marks,
    get_sync_status,
    get_my_teachers,
    get_teacher_timetable,
    get_gpa,
    get_lesson_detail,
    submit_homework,
    get_my_group,
    get_rating_book,
    list_notifications,
)
