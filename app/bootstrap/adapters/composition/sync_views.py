"""SyncViews over the marks module: sync failures and the newest sync run."""

from uuid import UUID

from app.bootstrap.adapters.composition.json_shape import json_object
from app.interfaces.http.v1.composition.ports import JsonObject
from app.modules.academic.application.marks.get_sync_failures import GetSyncFailures
from app.modules.academic.application.marks.list_sync_runs import ListSyncRuns
from app.shared.actor import Actor


class SyncViewsAdapter:
    """Composition <- academic marks: EMIS sync facts."""

    def __init__(
        self, get_sync_failures: GetSyncFailures, list_sync_runs: ListSyncRuns
    ) -> None:
        """Keep the two marks use cases."""
        self._get_sync_failures = get_sync_failures
        self._list_sync_runs = list_sync_runs

    async def sync_failures(self, user_id: UUID) -> int:
        """Return the student's consecutive failed syncs."""
        return await self._get_sync_failures.execute(user_id)

    async def last_sync_run(self, actor: Actor) -> JsonObject | None:
        """Return the newest `SyncRunItem` (the actor must be an administrator)."""
        page = await self._list_sync_runs.execute(actor, None, 1)
        return json_object(page.items[0]) if page.items else None
