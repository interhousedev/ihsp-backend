"""ORM models of the academic module (schema ``academic``)."""

from app.modules.academic.infrastructure.orm.assessment import Assessment
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.homework_todo import HomeworkTodo
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.mark import Mark
from app.modules.academic.infrastructure.orm.result import Result
from app.modules.academic.infrastructure.orm.room import Room
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.orm.sync_run import SyncRun
from app.modules.academic.infrastructure.orm.term import Term
from app.modules.academic.infrastructure.orm.timetable_entry import TimetableEntry

__all__ = [
    "Assessment",
    "Group",
    "HomeworkTodo",
    "Lesson",
    "Mark",
    "Result",
    "Room",
    "Student",
    "Subject",
    "SyncRun",
    "Term",
    "TimetableEntry",
]
