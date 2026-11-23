"""Composition of the engagement services (`container.lms.engagement`)."""

from app.modules.lms.application.engagement.service import EngagementService
from app.modules.lms.application.learning.audience import (
    AudienceGate,
    StudentGroupLookup,
)
from app.modules.lms.infrastructure.learning.engagement_uow import (
    SqlEngagementUnitOfWork,
)
from app.modules.lms.ports.learning.engagement import EngagementUnitOfWork
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


def build_engagement(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    student_group: StudentGroupLookup | None = None,
) -> EngagementService:
    """Return the engagement service over its own unit of work.

    The audience gate hides review items and flashcards of steps the learner may
    no longer open (no mastery lock: that check is the engagement service's own).
    """

    def uow_factory() -> EngagementUnitOfWork:
        return SqlEngagementUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return EngagementService(
        uow_factory, deps.clock, AudienceGate(identity, student_group)
    )
