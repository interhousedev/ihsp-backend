"""Builds the marks and EMIS sync services (task B5)."""

from dataclasses import dataclass

from app.modules.academic.application.marks.apply_ratings import ApplyRatings
from app.modules.academic.application.marks.backfill_student import BackfillStudent
from app.modules.academic.application.marks.get_day_grades import GetDayGrades
from app.modules.academic.application.marks.get_group_progress import (
    GetGroupProgress,
)
from app.modules.academic.application.marks.get_record_book import GetRecordBook
from app.modules.academic.application.marks.get_semester_grades import (
    GetSemesterGrades,
)
from app.modules.academic.application.marks.get_subject_detail import (
    GetSubjectDetail,
)
from app.modules.academic.application.marks.get_subject_planner import (
    GetSubjectPlanner,
)
from app.modules.academic.application.marks.get_sync_failures import GetSyncFailures
from app.modules.academic.application.marks.list_lesson_results import (
    ListLessonResults,
)
from app.modules.academic.application.marks.list_subject_lessons import (
    ListSubjectLessons,
)
from app.modules.academic.application.marks.list_subjects import ListSubjects
from app.modules.academic.application.marks.list_sync_runs import ListSyncRuns
from app.modules.academic.application.marks.ports.bell_sync import BellSync
from app.modules.academic.application.marks.ports.timetable_sync import (
    MaterialResync,
    TimetableSync,
)
from app.modules.academic.application.marks.resume_paused_sync import (
    ResumePausedSync,
)
from app.modules.academic.application.marks.resync_materials import ResyncMaterials
from app.modules.academic.application.marks.run_manual_sync import RunManualSync
from app.modules.academic.application.marks.stop_sync import (
    StopStudentSync,
    StopSyncRun,
)
from app.modules.academic.application.marks.sync_all import SyncAll
from app.modules.academic.application.marks.sync_student import SyncStudent
from app.modules.academic.application.public_marks import MarksQueriesImpl
from app.modules.academic.application.schedule.run_student_sync import (
    ListStudentSyncJobs,
    RetryStudentSyncs,
    RunStudentSync,
)
from app.modules.academic.application.schedule.student_sync_jobs import (
    StudentSyncJobs,
)
from app.modules.academic.application.schedule.sync_student_all import SyncStudentAll
from app.modules.academic.infrastructure.marks.sync_control import RedisSyncControl
from app.modules.academic.infrastructure.marks.uow import SqlMarksUnitOfWork
from app.modules.academic.wiring_schedule import sql_schedule_uow_factory
from app.shared.contracts.academic import AcademicEnrollment, ScheduleQueries
from app.shared.contracts.emis import EmisSource
from app.shared.contracts.identity import IdentityCommands, IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.emis_pause import EmisPause
from app.shared.redis_util import RedisKeyLock
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class MarksServices:
    """Use cases of marks and the EMIS sync, plus the `MarksQueries` contract."""

    sync_student: SyncStudent
    sync_all: SyncAll
    stop_sync_run: StopSyncRun
    stop_student_sync: StopStudentSync
    resume_paused_sync: ResumePausedSync
    backfill_student: BackfillStudent
    run_student_sync: RunStudentSync
    retry_student_syncs: RetryStudentSyncs
    list_student_sync_jobs: ListStudentSyncJobs
    run_manual_sync: RunManualSync
    resync_materials: ResyncMaterials
    list_sync_runs: ListSyncRuns
    list_subjects: ListSubjects
    get_subject_detail: GetSubjectDetail
    list_subject_lessons: ListSubjectLessons
    list_lesson_results: ListLessonResults
    get_subject_planner: GetSubjectPlanner
    get_semester_grades: GetSemesterGrades
    get_day_grades: GetDayGrades
    get_record_book: GetRecordBook
    get_sync_failures: GetSyncFailures
    get_group_progress: GetGroupProgress
    queries: MarksQueriesImpl


def build_marks(
    deps: ModuleDeps,
    *,
    emis: EmisSource,
    identity: IdentityDirectory,
    schedule: ScheduleQueries,
    identity_commands: IdentityCommands,
    enrollment: AcademicEnrollment,
    links: LinksApi,
    bell_sync: BellSync,
    timetable_sync: TimetableSync,
    material_resync: MaterialResync,
    sync_all_students: SyncStudentAll,
    sync_jobs: StudentSyncJobs,
) -> MarksServices:
    """Wire the marks use cases to SQL repositories and other modules' contracts."""

    def uow_factory() -> SqlMarksUnitOfWork:
        return SqlMarksUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    sync_student = SyncStudent(
        uow_factory=uow_factory,
        emis=emis,
        identity=identity,
        identity_commands=identity_commands,
        enrollment=enrollment,
        apply=ApplyRatings(clock=deps.clock),
        clock=deps.clock,
        kicker=deps.kicker,
        institution_id=deps.settings.emis.institution_id,
    )
    backfill_student = BackfillStudent(sync_student=sync_student)
    control = RedisSyncControl(deps.redis, EmisPause(deps.redis))
    sync_all_run = SyncAll(
        uow_factory=uow_factory,
        sync_student=sync_student,
        bell_sync=bell_sync,
        timetable_sync=timetable_sync,
        identity=identity,
        clock=deps.clock,
        lock=RedisKeyLock(deps.redis),
        control=control,
    )
    return MarksServices(
        sync_student=sync_student,
        sync_all=sync_all_run,
        backfill_student=backfill_student,
        run_student_sync=RunStudentSync(
            jobs=sync_jobs,
            sync_all=sync_all_students,
            backfill=backfill_student,
            uow_factory=sql_schedule_uow_factory(deps),
            clock=deps.clock,
            identity=identity,
            control=control,
        ),
        retry_student_syncs=RetryStudentSyncs(
            jobs=sync_jobs, kicker=deps.kicker, clock=deps.clock
        ),
        list_student_sync_jobs=ListStudentSyncJobs(jobs=sync_jobs),
        stop_sync_run=StopSyncRun(uow_factory=uow_factory, control=control),
        stop_student_sync=StopStudentSync(jobs=sync_jobs, control=control),
        resume_paused_sync=ResumePausedSync(control=control, sync_all=sync_all_run),
        run_manual_sync=RunManualSync(
            uow_factory=uow_factory,
            schedule=schedule,
            kicker=deps.kicker,
            clock=deps.clock,
        ),
        resync_materials=ResyncMaterials(
            uow_factory=uow_factory,
            materials=material_resync,
            group_concurrency=deps.settings.emis.group_concurrency,
        ),
        list_sync_runs=ListSyncRuns(uow_factory=uow_factory),
        list_subjects=ListSubjects(
            uow_factory=uow_factory, identity=identity, clock=deps.clock
        ),
        get_subject_detail=GetSubjectDetail(
            uow_factory=uow_factory, identity=identity, links=links, clock=deps.clock
        ),
        list_lesson_results=ListLessonResults(
            uow_factory=uow_factory, clock=deps.clock
        ),
        list_subject_lessons=ListSubjectLessons(
            uow_factory=uow_factory, links=links, clock=deps.clock
        ),
        get_subject_planner=GetSubjectPlanner(
            uow_factory=uow_factory, identity=identity
        ),
        get_semester_grades=GetSemesterGrades(
            uow_factory=uow_factory, identity=identity, clock=deps.clock
        ),
        get_day_grades=GetDayGrades(uow_factory=uow_factory, identity=identity),
        get_record_book=GetRecordBook(
            uow_factory=uow_factory, identity=identity, clock=deps.clock
        ),
        get_sync_failures=GetSyncFailures(uow_factory=uow_factory),
        get_group_progress=GetGroupProgress(
            uow_factory=uow_factory, identity=identity, clock=deps.clock
        ),
        queries=MarksQueriesImpl(
            uow_factory=uow_factory, identity=identity, clock=deps.clock
        ),
    )
