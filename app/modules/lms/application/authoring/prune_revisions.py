"""Use case: delete old checkpoints and previews (LMS-12, daily job)."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.shared.clock import Clock

CHECKPOINTS_KEPT = 20
PREVIEW_RETENTION = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class PruneResult:
    """How many revisions a prune run deleted."""

    checkpoints: int
    previews: int


class PruneRevisions:
    """Keep the newest 20 checkpoints per step and 30 days of previews.

    Revisions that were published or are used by attempts are never deleted.
    """

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self) -> PruneResult:
        """Delete what is beyond the limits and commit."""
        async with self.uow_factory() as uow:
            checkpoints = await uow.revisions.prune_checkpoints(keep=CHECKPOINTS_KEPT)
            previews = await uow.revisions.prune_previews(
                older_than=self.clock.now() - PREVIEW_RETENTION
            )
            await uow.commit()
        return PruneResult(checkpoints=checkpoints, previews=previews)
