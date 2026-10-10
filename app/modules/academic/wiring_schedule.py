"""Wiring of the academic schedule: use cases, queries and enrollment."""

from dataclasses import dataclass

from app.modules.academic.application.public_schedule import (
    AcademicEnrollmentImpl,
    ScheduleQueriesImpl,
)
from app.modules.academic.application.schedule.archive_room import ArchiveRoom
from app.modules.academic.application.schedule.assign_subgroups import AssignSubgroups
from app.modules.academic.application.schedule.calendar_token import (
    RotateCalendarToken,
    UserForCalendarToken,
)
from app.modules.academic.application.schedule.check_entry import CheckEntry
from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.copy_timetable import CopyTimetable
from app.modules.academic.application.schedule.create_entry import CreateEntry
from app.modules.academic.application.schedule.create_extra_lesson import (
    CreateExtraLesson,
)
from app.modules.academic.application.schedule.create_group import CreateGroup
from app.modules.academic.application.schedule.create_subject import CreateSubject
from app.modules.academic.application.schedule.create_term import CreateTerm
from app.modules.academic.application.schedule.current_term import CurrentTerm
from app.modules.academic.application.schedule.delete_entry import DeleteEntry
from app.modules.academic.application.schedule.ensure_room import EnsureRoom
from app.modules.academic.application.schedule.generate_lessons import GenerateLessons
from app.modules.academic.application.schedule.get_group_detail import GetGroupDetail
from app.modules.academic.application.schedule.get_my_teachers import GetMyTeachers
from app.modules.academic.application.schedule.get_staff_timetable import (
    GetStaffTimetable,
)
from app.modules.academic.application.schedule.get_student_timetable import (
    GetStudentTimetable,
)
from app.modules.academic.application.schedule.import_confirm import ImportConfirm
from app.modules.academic.application.schedule.import_preview import ImportPreview
from app.modules.academic.application.schedule.list_curated_groups import (
    ListCuratedGroups,
)
from app.modules.academic.application.schedule.list_entries import ListEntries
from app.modules.academic.application.schedule.list_groups import ListGroups
from app.modules.academic.application.schedule.list_lessons import ListLessons
from app.modules.academic.application.schedule.list_rooms import ListRooms
from app.modules.academic.application.schedule.list_students import ListStudents
from app.modules.academic.application.schedule.list_subjects import ListSubjects
from app.modules.academic.application.schedule.list_terms import ListTerms
from app.modules.academic.application.schedule.merge_room import MergeRoom
from app.modules.academic.application.schedule.ports.import_store import ImportStore
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.regenerate_room_pin import (
    RegenerateRoomPin,
)
from app.modules.academic.application.schedule.rename_room import RenameRoom
from app.modules.academic.application.schedule.student_profile import (
    GetStudentProfile,
)
from app.modules.academic.application.schedule.teacher_deactivated import (
    TeacherDeactivated,
)
from app.modules.academic.application.schedule.update_entry import UpdateEntry
from app.modules.academic.application.schedule.update_group import UpdateGroup
from app.modules.academic.application.schedule.update_lesson import UpdateLesson
from app.modules.academic.application.schedule.update_subject import UpdateSubject
from app.modules.academic.application.schedule.update_term import UpdateTerm
from app.modules.academic.infrastructure.schedule.import_store import RedisImportStore
from app.modules.academic.infrastructure.schedule.reader import SqlScheduleReader
from app.modules.academic.infrastructure.schedule.room_page_cache import (
    RedisRoomPageCache,
)
from app.modules.academic.infrastructure.schedule.uow import SqlScheduleUnitOfWork
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityCommands, IdentityDirectory
from app.shared.tasks import TaskKicker
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class ScheduleServices:
    """Use cases of the schedule plus its public contract objects."""

    create_term: CreateTerm
    update_term: UpdateTerm
    list_terms: ListTerms
    current_term: CurrentTerm
    create_group: CreateGroup
    update_group: UpdateGroup
    assign_subgroups: AssignSubgroups
    get_group_detail: GetGroupDetail
    list_groups: ListGroups
    list_curated_groups: ListCuratedGroups
    list_subjects: ListSubjects
    create_subject: CreateSubject
    update_subject: UpdateSubject
    ensure_room: EnsureRoom
    list_rooms: ListRooms
    rename_room: RenameRoom
    regenerate_room_pin: RegenerateRoomPin
    merge_room: MergeRoom
    archive_room: ArchiveRoom
    create_entry: CreateEntry
    update_entry: UpdateEntry
    delete_entry: DeleteEntry
    check_entry: CheckEntry
    copy_timetable: CopyTimetable
    list_entries: ListEntries
    generate_lessons: GenerateLessons
    list_lessons: ListLessons
    create_extra_lesson: CreateExtraLesson
    update_lesson: UpdateLesson
    teacher_deactivated: TeacherDeactivated
    list_students: ListStudents
    import_preview: ImportPreview
    import_confirm: ImportConfirm
    get_student_profile: GetStudentProfile
    get_student_timetable: GetStudentTimetable
    get_my_teachers: GetMyTeachers
    get_staff_timetable: GetStaffTimetable
    rotate_calendar_token: RotateCalendarToken
    user_for_calendar_token: UserForCalendarToken
    queries: ScheduleQueriesImpl
    enrollment: AcademicEnrollmentImpl


def assemble_schedule(
    *,
    uow_factory: UowFactory,
    reader: ScheduleReader,
    import_store: ImportStore,
    room_cache: RoomPageCache,
    clock: Clock,
    kicker: TaskKicker,
    identity: IdentityDirectory,
    identity_commands: IdentityCommands,
    rooms_url: str,
    mail_domain: str,
) -> ScheduleServices:
    """Connect use cases to the given ports (real or fake)."""
    return ScheduleServices(
        create_term=CreateTerm(uow_factory, clock),
        update_term=UpdateTerm(uow_factory, clock, kicker),
        list_terms=ListTerms(uow_factory, clock),
        current_term=CurrentTerm(uow_factory, clock),
        create_group=CreateGroup(uow_factory, identity),
        update_group=UpdateGroup(uow_factory, identity),
        assign_subgroups=AssignSubgroups(uow_factory, identity, clock),
        get_group_detail=GetGroupDetail(uow_factory, identity),
        list_groups=ListGroups(uow_factory, identity),
        list_curated_groups=ListCuratedGroups(uow_factory, identity),
        list_subjects=ListSubjects(uow_factory),
        create_subject=CreateSubject(uow_factory),
        update_subject=UpdateSubject(uow_factory),
        ensure_room=EnsureRoom(uow_factory, clock),
        list_rooms=ListRooms(uow_factory, clock, rooms_url),
        rename_room=RenameRoom(uow_factory, clock, room_cache, rooms_url),
        regenerate_room_pin=RegenerateRoomPin(
            uow_factory, clock, room_cache, rooms_url
        ),
        merge_room=MergeRoom(uow_factory, clock, room_cache, rooms_url),
        archive_room=ArchiveRoom(uow_factory, clock, rooms_url),
        create_entry=CreateEntry(uow_factory, identity, clock, kicker),
        update_entry=UpdateEntry(uow_factory, identity, clock, kicker),
        delete_entry=DeleteEntry(uow_factory, clock, kicker, room_cache),
        check_entry=CheckEntry(uow_factory, clock),
        copy_timetable=CopyTimetable(uow_factory, clock, kicker),
        list_entries=ListEntries(uow_factory, identity, clock),
        generate_lessons=GenerateLessons(uow_factory, clock, kicker, room_cache),
        list_lessons=ListLessons(reader, identity),
        create_extra_lesson=CreateExtraLesson(
            uow_factory, reader, identity, clock, kicker, room_cache
        ),
        update_lesson=UpdateLesson(
            uow_factory, reader, identity, clock, kicker, room_cache
        ),
        teacher_deactivated=TeacherDeactivated(uow_factory, clock),
        list_students=ListStudents(uow_factory, identity),
        import_preview=ImportPreview(uow_factory, identity, import_store),
        import_confirm=ImportConfirm(uow_factory, identity_commands, import_store),
        get_student_profile=GetStudentProfile(uow_factory, identity, mail_domain),
        get_student_timetable=GetStudentTimetable(reader, identity, clock),
        get_my_teachers=GetMyTeachers(reader, identity, clock),
        get_staff_timetable=GetStaffTimetable(reader, identity, clock),
        rotate_calendar_token=RotateCalendarToken(uow_factory),
        user_for_calendar_token=UserForCalendarToken(uow_factory),
        queries=ScheduleQueriesImpl(reader),
        enrollment=AcademicEnrollmentImpl(uow_factory, identity, clock, kicker),
    )


def sql_schedule_uow_factory(deps: ModuleDeps) -> UowFactory:
    """Units of work over PostgreSQL, with the outbox and audit writers of the deps."""

    def uow_factory() -> SqlScheduleUnitOfWork:
        return SqlScheduleUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return uow_factory


def build_schedule(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    identity_commands: IdentityCommands,
) -> ScheduleServices:
    """Build the schedule services on PostgreSQL and Redis."""
    return assemble_schedule(
        uow_factory=sql_schedule_uow_factory(deps),
        reader=SqlScheduleReader(deps.sessionmaker),
        import_store=RedisImportStore(deps.redis),
        room_cache=RedisRoomPageCache(deps.redis),
        clock=deps.clock,
        kicker=deps.kicker,
        identity=identity,
        identity_commands=identity_commands,
        rooms_url=deps.settings.urls.rooms,
        mail_domain=deps.settings.smtp_out.mail_domain,
    )
