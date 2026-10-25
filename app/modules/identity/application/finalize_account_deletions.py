"""Close accounts whose deletion window ran out (part of identity.purge_deleted_users).

A pending account becomes ``deleted`` with ``deleted_at`` = the request time, so
the anonymizing purge (same job, next run) picks it up after the clean-up tasks
started here have removed its files and the EMIS secret.
"""

from datetime import timedelta
from functools import partial

from app.modules.identity.application.register_ports import (
    AccountRevokerPort,
    UnitOfWorkFactory,
)
from app.shared.clock import Clock
from app.shared.contracts.academic import AcademicEnrollment
from app.shared.notifications import AuditDraft
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

BATCH = 200
CLEANUP_TASKS = (
    "identity.destroy_emis_secret",
    "files.delete_owner",
    "links.revoke_owner",
    "notebooks.delete_owner",
    "library.delete_owner",
)


class FinalizeAccountDeletions:
    """Turn expired ``pending_deletion`` accounts into ``deleted`` ones."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        revoker: AccountRevokerPort,
        enrollment: AcademicEnrollment,
        kicker: TaskKicker,
        clock: Clock,
        retention_days: int,
    ) -> None:
        """Store the collaborators."""
        self._uow_factory = uow_factory
        self._revoker = revoker
        self._enrollment = enrollment
        self._kicker = kicker
        self._clock = clock
        self._retention = timedelta(days=retention_days)

    async def execute(self) -> int:
        """Return how many accounts were closed."""
        cutoff = self._clock.now() - self._retention
        async with self._uow_factory() as uow:
            due = await uow.accounts.deletion_due(cutoff, BATCH)
        closed = 0
        for user_id in due:
            async with self._uow_factory() as uow:
                if not await uow.accounts.finalize_deletion(user_id):
                    continue  # restored in the meantime
                uow.audit(AuditDraft(type="account.deleted", user_id=user_id))
                for task in CLEANUP_TASKS:
                    uow.after_commit(
                        partial(self._kicker.kick, task, user_id=str(user_id))
                    )
                await uow.commit()
            closed += 1
            # mark_left queues the account_closing notice before the links go.
            await self._enrollment.mark_left(user_id, reason="deleted")
            await self._revoker.revoke_everything(user_id)
        log.info("account_deletions_finalized", closed=closed)
        return closed
