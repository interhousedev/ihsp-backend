"""Composition of the LMS facts read by course certificates."""

from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.certificate_facts import (
    LmsCertificateFacts,
)
from app.modules.lms.infrastructure.learning.uow import SqlLearningUnitOfWork
from app.modules.lms.wiring import LmsModule, _student_group
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


def build_certificate_facts(
    deps: ModuleDeps,
    lms: LmsModule,
    *,
    identity: IdentityDirectory,
    students: ScheduleQueries,
) -> LmsCertificateFacts:
    """Return the facts; course writers (and LMS admins) manage certificates."""

    def uow_factory() -> SqlLearningUnitOfWork:
        return SqlLearningUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    async def can_manage(user_id: UUID, course_id: UUID) -> bool:
        access = await lms.authoring.workspace.course_access(user_id, course_id)
        return access is not None and access.can_write

    gate = AudienceGate(identity, _student_group(students))
    return LmsCertificateFacts(uow_factory, gate, can_manage)
