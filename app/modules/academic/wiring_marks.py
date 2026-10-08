"""Builds the marks and EMIS sync services (task B5)."""

from dataclasses import dataclass

from app.modules.academic.application.marks.apply_ratings import ApplyRatings
from app.modules.academic.application.marks.backfill_student import BackfillStudent
from app.modules.academic.application.marks.get_day_grades import GetDayGrades
from app.modules.academic.application.marks.get_record_book import GetRecordBook
from app.modules.academic.application.marks.get_semester_grades import (
    GetSemesterGrades,
)
from app.modules.academic.application.marks.get_subject_detail import (
    GetSubjectDetail,
)
from app.modules.academic.application.marks.get_sync_failures import GetSyncFailures
from app.modules.academic.application.marks.list_subjects import ListSubjects
from app.modules.academic.application.marks.list_sync_runs import ListSyncRuns
from app.modules.academic.application.marks.ports.bell_sync import BellSync
from app.modules.academic.application.marks.run_manual_sync import RunManualSync
from app.modules.academic.application.marks.sync_all import SyncAll
from app.modules.academic.application.marks.sync_student import SyncStudent
from app.modules.academic.application.public_marks import MarksQueriesImpl
from app.modules.academic.infrastructure.marks.uow import SqlMarksUnitOfWork
from app.shared.contracts.academic import AcademicEnrollment, ScheduleQueries
from app.shared.contracts.emis import EmisSource
from app.shared.contracts.identity import IdentityCommands, IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class MarksServices:
    """Use cases of marks and the EMIS sync, plus the `MarksQueries` contract."""

    sync_student: SyncStudent
    sync_all: SyncAll
    backfill_student: BackfillStudent
    run_manual_sync: RunManualSync
    list_sync_runs: ListSyncRuns
    list_subjects: ListSubjects
    get_subject_detail: GetSubjectDetail
    get_semester_grades: GetSemesterGrades
    get_day_grades: GetDayGrades
    get_record_book: GetRecordBook
    get_sync_failures: GetSyncFailures
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
    return MarksServices(
        sync_student=sync_student,
        sync_all=SyncAll(
            uow_factory=uow_factory,
            sync_student=sync_student,
            bell_sync=bell_sync,
            identity=identity,
            clock=deps.clock,
        ),
        backfill_student=BackfillStudent(sync_student=sync_student),
        run_manual_sync=RunManualSync(
            uow_factory=uow_factory,
            schedule=schedule,
            kicker=deps.kicker,
            clock=deps.clock,
        ),
        list_sync_runs=ListSyncRuns(uow_factory=uow_factory),
        list_subjects=ListSubjects(
            uow_factory=uow_factory, identity=identity, clock=deps.clock
        ),
        get_subject_detail=GetSubjectDetail(
            uow_factory=uow_factory, identity=identity, links=links, clock=deps.clock
        ),
        get_semester_grades=GetSemesterGrades(
            uow_factory=uow_factory, identity=identity
        ),
        get_day_grades=GetDayGrades(uow_factory=uow_factory, identity=identity),
        get_record_book=GetRecordBook(uow_factory=uow_factory, identity=identity),
        get_sync_failures=GetSyncFailures(uow_factory=uow_factory),
        queries=MarksQueriesImpl(
            uow_factory=uow_factory, identity=identity, clock=deps.clock
        ),
    )
