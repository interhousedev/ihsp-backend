"""Builds the classwork services (homework, attendance, journal, lesson views)."""

from dataclasses import dataclass

from app.modules.academic.application.classwork.attendance_report import (
    AttendanceReport,
)
from app.modules.academic.application.classwork.attendance_report_csv import (
    AttendanceReportCsv,
)
from app.modules.academic.application.classwork.attendance_sheet import (
    AttendanceSheetBuilder,
)
from app.modules.academic.application.classwork.clear_homework import ClearHomework
from app.modules.academic.application.classwork.curator_students import (
    CuratorStudents,
)
from app.modules.academic.application.classwork.get_attendance_sheet import (
    GetAttendanceSheet,
)
from app.modules.academic.application.classwork.get_journal import GetJournal
from app.modules.academic.application.classwork.get_prompt_state import GetPromptState
from app.modules.academic.application.classwork.group_attendance import GroupAttendance
from app.modules.academic.application.classwork.group_attendance_csv import (
    GroupAttendanceCsv,
)
from app.modules.academic.application.classwork.homework_items import (
    HomeworkItemBuilder,
)
from app.modules.academic.application.classwork.homework_list import HomeworkList
from app.modules.academic.application.classwork.journal_csv import JournalCsv
from app.modules.academic.application.classwork.journal_options import JournalOptions
from app.modules.academic.application.classwork.lesson_items import LessonItemBuilder
from app.modules.academic.application.classwork.lesson_reminders import (
    LessonReminders,
)
from app.modules.academic.application.classwork.missing_attendance import (
    MissingAttendance,
)
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.prompt_state_builder import (
    PromptStateBuilder,
)
from app.modules.academic.application.classwork.recompute_due_dates import (
    RecomputeDueDates,
)
from app.modules.academic.application.classwork.report_format import ReportFormatter
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.application.classwork.set_excuse import SetExcuse
from app.modules.academic.application.classwork.set_homework import SetHomework
from app.modules.academic.application.classwork.set_homework_done import (
    SetHomeworkDone,
)
from app.modules.academic.application.classwork.set_homework_note import (
    SetHomeworkNote,
)
from app.modules.academic.application.classwork.set_topic import SetTopic
from app.modules.academic.application.classwork.staff_clear_homework import (
    StaffClearHomework,
)
from app.modules.academic.application.classwork.staff_lesson import StaffLesson
from app.modules.academic.application.classwork.staff_set_homework import (
    StaffSetHomework,
)
from app.modules.academic.application.classwork.staff_set_topic import StaffSetTopic
from app.modules.academic.application.classwork.staff_today import StaffToday
from app.modules.academic.application.classwork.student_attendance import (
    StudentAttendance,
)
from app.modules.academic.application.classwork.student_context import StudyDays
from app.modules.academic.application.classwork.student_lesson import StudentLesson
from app.modules.academic.application.classwork.student_today import StudentToday
from app.modules.academic.application.classwork.submit_attendance import (
    SubmitAttendance,
)
from app.modules.academic.application.classwork.submit_from_draft import SubmitFromDraft
from app.modules.academic.application.classwork.toggle_draft_absent import (
    ToggleDraftAbsent,
)
from app.modules.academic.application.classwork.toggle_journal_cell import (
    ToggleJournalCell,
)
from app.modules.academic.application.public_classwork import (
    ClassworkCommandsImpl,
    ClassworkQueriesImpl,
)
from app.modules.academic.infrastructure.classwork.draft_store import (
    RedisAttendanceDraftStore,
)
from app.modules.academic.infrastructure.classwork.uow import SqlClassworkUnitOfWork
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class ClassworkServices:
    """Use cases (attribute name = file name) and the public contract objects."""

    get_attendance_sheet: GetAttendanceSheet
    submit_attendance: SubmitAttendance
    toggle_journal_cell: ToggleJournalCell
    set_excuse: SetExcuse
    get_prompt_state: GetPromptState
    toggle_draft_absent: ToggleDraftAbsent
    submit_from_draft: SubmitFromDraft
    set_homework: SetHomework
    clear_homework: ClearHomework
    set_topic: SetTopic
    recompute_due_dates: RecomputeDueDates
    staff_set_homework: StaffSetHomework
    staff_clear_homework: StaffClearHomework
    staff_set_topic: StaffSetTopic
    homework_list: HomeworkList
    set_homework_done: SetHomeworkDone
    set_homework_note: SetHomeworkNote
    student_today: StudentToday
    student_lesson: StudentLesson
    staff_today: StaffToday
    staff_lesson: StaffLesson
    student_attendance: StudentAttendance
    group_attendance: GroupAttendance
    group_attendance_csv: GroupAttendanceCsv
    attendance_report: AttendanceReport
    attendance_report_csv: AttendanceReportCsv
    missing_attendance: MissingAttendance
    journal_options: JournalOptions
    get_journal: GetJournal
    journal_csv: JournalCsv
    curator_students: CuratorStudents
    lesson_reminders: LessonReminders
    queries: ClassworkQueriesImpl
    commands: ClassworkCommandsImpl


def build_classwork(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    schedule: ScheduleQueries,
    links: LinksApi,
) -> ClassworkServices:
    """Wire the classwork use cases over the shared infrastructure."""
    settings = deps.settings
    clock = deps.clock
    edit_days = settings.limits.attendance_edit_days

    def uow_factory() -> SqlClassworkUnitOfWork:
        return SqlClassworkUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    people = PeopleDirectory(identity)
    lesson_items = LessonItemBuilder(people)
    homework_items = HomeworkItemBuilder(people, clock)
    roster_loader = RosterLoader(people)
    sheets = AttendanceSheetBuilder(people)
    study_days = StudyDays(schedule)
    formatter = ReportFormatter(people)
    drafts = RedisAttendanceDraftStore(deps.redis)
    prompts = PromptStateBuilder(clock, roster_loader, drafts)

    submit = SubmitAttendance(uow_factory, clock, roster_loader, sheets)
    set_homework = SetHomework(uow_factory, clock)
    clear_homework = ClearHomework(uow_factory, clock)
    set_topic = SetTopic(uow_factory, clock)
    set_homework_done = SetHomeworkDone(uow_factory, clock, people, homework_items)
    get_prompt_state = GetPromptState(uow_factory, people, drafts, prompts)
    toggle_draft = ToggleDraftAbsent(uow_factory, clock, people, drafts, prompts)
    submit_from_draft = SubmitFromDraft(uow_factory, people, drafts, submit, prompts)
    homework_list = HomeworkList(uow_factory, clock, people, homework_items, study_days)
    staff_lesson = StaffLesson(
        uow_factory,
        clock,
        people,
        lesson_items,
        roster_loader,
        sheets,
        schedule,
        links,
    )
    group_attendance = GroupAttendance(uow_factory, clock, people, formatter, schedule)
    attendance_report = AttendanceReport(uow_factory, clock, people, formatter)
    get_journal = GetJournal(uow_factory, clock, people, roster_loader)

    return ClassworkServices(
        get_attendance_sheet=GetAttendanceSheet(
            uow_factory, clock, roster_loader, sheets
        ),
        submit_attendance=submit,
        toggle_journal_cell=ToggleJournalCell(
            uow_factory, clock, roster_loader, sheets
        ),
        set_excuse=SetExcuse(uow_factory, clock, roster_loader, sheets, schedule),
        get_prompt_state=get_prompt_state,
        toggle_draft_absent=toggle_draft,
        submit_from_draft=submit_from_draft,
        set_homework=set_homework,
        clear_homework=clear_homework,
        set_topic=set_topic,
        recompute_due_dates=RecomputeDueDates(uow_factory),
        staff_set_homework=StaffSetHomework(set_homework, staff_lesson),
        staff_clear_homework=StaffClearHomework(clear_homework, staff_lesson),
        staff_set_topic=StaffSetTopic(set_topic, staff_lesson),
        homework_list=homework_list,
        set_homework_done=set_homework_done,
        set_homework_note=SetHomeworkNote(uow_factory, clock, people, homework_items),
        student_today=StudentToday(
            uow_factory,
            clock,
            people,
            lesson_items,
            homework_list,
            study_days,
            links,
        ),
        student_lesson=StudentLesson(
            uow_factory, clock, people, lesson_items, homework_items, links
        ),
        staff_today=StaffToday(uow_factory, clock, people, lesson_items, edit_days),
        staff_lesson=staff_lesson,
        student_attendance=StudentAttendance(uow_factory, clock, people, lesson_items),
        group_attendance=group_attendance,
        group_attendance_csv=GroupAttendanceCsv(group_attendance, people, deps.i18n),
        attendance_report=attendance_report,
        attendance_report_csv=AttendanceReportCsv(attendance_report, people, deps.i18n),
        missing_attendance=MissingAttendance(uow_factory, clock, people, lesson_items),
        journal_options=JournalOptions(uow_factory, clock, people),
        get_journal=get_journal,
        journal_csv=JournalCsv(get_journal, people, deps.i18n),
        curator_students=CuratorStudents(uow_factory, clock, identity, schedule),
        lesson_reminders=LessonReminders(
            uow_factory, clock, people, schedule, links, settings.urls.rooms
        ),
        queries=ClassworkQueriesImpl(uow_factory, clock, people),
        commands=ClassworkCommandsImpl(
            people,
            get_prompt_state,
            toggle_draft,
            submit_from_draft,
            set_homework,
            clear_homework,
            set_topic,
            set_homework_done,
        ),
    )
