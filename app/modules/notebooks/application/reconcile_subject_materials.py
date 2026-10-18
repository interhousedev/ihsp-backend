"""Check that every lesson material of a subject is in its subject notebooks."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.sync_auto_notebook import SyncAutoNotebook
from app.modules.notebooks.ports.unit_of_work import UowFactory

RECONCILE_LIMIT = 1000  # subject notebooks checked by one request


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Totals over the subject notebooks that were checked."""

    notebooks: int = 0
    added: int = 0
    already_present: int = 0
    skipped: int = 0  # materials not readable yet (a later sweep takes them)


class ReconcileSubjectMaterials:
    """Runs the auto sync of each subject notebook now, and reports what it found.

    The sync is idempotent: a material already in a notebook is counted as present
    and never added twice. Admins check every student's subject notebook of the
    subject (`owner_id` None); a teacher checks their own.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        sync: SyncAutoNotebook,
        limit: int = RECONCILE_LIMIT,
    ) -> None:
        """Store the collaborators and the number of notebooks one run may check."""
        self.uow_factory = uow_factory
        self.sync = sync
        self.limit = limit

    async def execute(
        self, subject_id: UUID, owner_id: UUID | None = None
    ) -> ReconcileResult:
        """Sync each subject notebook of the subject; return the totals."""
        async with self.uow_factory() as uow:
            ids = await uow.notebooks.auto_subject_ids(subject_id, owner_id, self.limit)
        added = present = skipped = 0
        for notebook_id in ids:
            result = await self.sync.execute(notebook_id)
            added += result.added
            present += result.present
            skipped += result.skipped
        return ReconcileResult(
            notebooks=len(ids),
            added=added,
            already_present=present,
            skipped=skipped,
        )
