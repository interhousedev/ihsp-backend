"""Builds the assessments services: exam calendar, staff editor, EMIS suggestions."""

from dataclasses import dataclass

from app.modules.academic.application.assessments.create_assessment import (
    CreateAssessment,
)
from app.modules.academic.application.assessments.delete_assessment import (
    DeleteAssessment,
)
from app.modules.academic.application.assessments.generate_tentative import (
    GenerateTentativeAssessments,
)
from app.modules.academic.application.assessments.list_my_assessments import (
    ListMyAssessments,
)
from app.modules.academic.application.assessments.list_staff_assessments import (
    ListStaffAssessments,
)
from app.modules.academic.application.assessments.propose_assessment import (
    ProposeAssessment,
)
from app.modules.academic.application.assessments.send_reminders import (
    SendAssessmentReminders,
)
from app.modules.academic.application.assessments.update_assessment import (
    UpdateAssessment,
)
from app.modules.academic.application.public_schedule import ScheduleQueriesImpl
from app.modules.academic.infrastructure.assessments.uow import (
    SqlAssessmentsUnitOfWork,
)
from app.modules.academic.infrastructure.schedule.reader import SqlScheduleReader
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class AssessmentServices:
    """Use cases of assessments (midterm and final controls)."""

    list_mine: ListMyAssessments
    propose: ProposeAssessment
    list_staff: ListStaffAssessments
    create: CreateAssessment
    update: UpdateAssessment
    delete: DeleteAssessment
    generate_suggestions: GenerateTentativeAssessments
    send_reminders: SendAssessmentReminders


def build_assessments(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    schedule: ScheduleQueries | None = None,
) -> AssessmentServices:
    """Wire the assessments use cases to SQL repositories.

    EMIS control lessons are read through ``schedule.emis_control_lessons``; without
    one, the schedule's own queries are built over the same database.
    """
    schedule = schedule or ScheduleQueriesImpl(SqlScheduleReader(deps.sessionmaker))

    def uow_factory() -> SqlAssessmentsUnitOfWork:
        return SqlAssessmentsUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    clock = deps.clock
    return AssessmentServices(
        list_mine=ListMyAssessments(
            uow_factory=uow_factory, identity=identity, clock=clock
        ),
        propose=ProposeAssessment(
            uow_factory=uow_factory, identity=identity, clock=clock
        ),
        list_staff=ListStaffAssessments(
            uow_factory=uow_factory, identity=identity, clock=clock
        ),
        create=CreateAssessment(
            uow_factory=uow_factory, identity=identity, clock=clock
        ),
        update=UpdateAssessment(
            uow_factory=uow_factory, identity=identity, clock=clock
        ),
        delete=DeleteAssessment(uow_factory=uow_factory, clock=clock),
        generate_suggestions=GenerateTentativeAssessments(
            uow_factory=uow_factory, schedule=schedule, clock=clock
        ),
        send_reminders=SendAssessmentReminders(
            uow_factory=uow_factory, identity=identity, clock=clock
        ),
    )
