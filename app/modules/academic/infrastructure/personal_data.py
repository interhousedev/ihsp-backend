"""Personal-data specification of the academic module (export and erasure)."""

from app.modules.academic.infrastructure.orm.emis_attendance import EmisAttendance
from app.modules.academic.infrastructure.orm.excuse import Excuse, ExcuseMessage
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.homework_submission import (
    HomeworkSubmission,
)
from app.modules.academic.infrastructure.orm.homework_todo import HomeworkTodo
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.mark import Mark
from app.modules.academic.infrastructure.orm.result import Result
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.student_sync_job import StudentSyncJob
from app.modules.academic.infrastructure.orm.temporary_mark import TemporaryMark
from app.modules.academic.infrastructure.orm.timetable_entry import TimetableEntry
from app.modules.academic.infrastructure.orm.work_off import WorkOff, WorkOffTemplate
from app.shared.personal_data import (
    ParentLink,
    PersonalTable,
    SqlPersonalData,
    Treatment,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

E, N, R = Treatment.ERASE, Treatment.NULLIFY, Treatment.RETAIN
_ = ParentLink

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(HomeworkTodo, E, owner="student_id", note="personal to-do list"),
    PersonalTable(StudentSyncJob, E, owner="user_id", note="EMIS sync queue"),
    PersonalTable(EmisAttendance, R, owner="student_id", note="school record"),
    PersonalTable(ExcuseMessage, R, owner="author_id", note="school record"),
    PersonalTable(Excuse, R, owner="student_id", note="school record"),
    PersonalTable(HomeworkSubmission, R, owner="student_id", note="school record"),
    PersonalTable(Mark, R, owner="student_id", note="school record"),
    PersonalTable(Result, R, owner="student_id", note="school record"),
    PersonalTable(TemporaryMark, R, owner="student_id", note="school record"),
    PersonalTable(WorkOff, R, owner="student_id", note="school record"),
    PersonalTable(WorkOffTemplate, R, owner="teacher_id", note="school record"),
    PersonalTable(Student, R, owner="user_id", note="school roster"),
    PersonalTable(Lesson, R, owner="teacher_id", note="timetable reference"),
    PersonalTable(TimetableEntry, R, owner="teacher_id", note="timetable reference"),
    PersonalTable(Group, R, owner="head_student_id", note="class head reference"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
