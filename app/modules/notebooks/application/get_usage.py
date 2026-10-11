"""Use case: the student's budget, quotas and running outputs (NB-14)."""

from uuid import UUID

from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.application.views import (
    NotebookUsageView,
    QuotaView,
    UsagePartView,
)
from app.settings import Settings
from app.shared.limits import LimitsProvider, StaticLimits


class GetUsage:
    """Reads `GET /v1/notebooks/usage`."""

    def __init__(
        self,
        budget: NotebookBudget,
        quota: QuotaService,
        settings: Settings,
        limits: LimitsProvider | None = None,
    ) -> None:
        """Store the services and the limits provider."""
        self.budget = budget
        self.quota = quota
        self.settings = settings
        self.limits = limits or StaticLimits(settings.limits)

    async def execute(
        self, user_id: UUID, *, course: bool = False
    ) -> NotebookUsageView:
        """Return the session and day budget, the four quotas and the running count.

        `course=True` reads the pool of course workspaces (course staff).
        """
        budget, quota = self.budget.pool(course), self.quota.pool(course)
        info = await budget.usage(user_id)
        quotas = await quota.snapshot(user_id)
        return NotebookUsageView(
            session=UsagePartView(
                info.session.used, info.session.limit, info.session.resets_at
            ),
            day=UsagePartView(info.day.used, info.day.limit, info.day.resets_at),
            quotas={
                name: QuotaView(part.used, part.limit, part.resets_at)
                for name, part in quotas.items()
            },
            generating=await quota.running_count(user_id),
            generating_limit=(await self.limits.current()).nb_concurrent_artifacts,
        )
