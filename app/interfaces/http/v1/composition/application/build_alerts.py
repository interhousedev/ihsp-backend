"""Use case: alerts on the student's Today page (WEB-3)."""

import datetime as dt

from app.interfaces.http.v1.composition.ports import FilesViews, JsonObject, SyncViews
from app.settings import UrlsSettings
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.identity import IdentityDirectory

# Files are deleted at the end of the term (FILE-5); warn a week ahead.
FILES_WARNING_DAYS = 7


def _alert(kind: str, action_url: str, **params: object) -> JsonObject:
    return {"kind": kind, "params": params, "action_url": action_url}


class BuildAlerts:
    """Collects what needs the student's attention, most important first."""

    def __init__(
        self,
        *,
        identity: IdentityDirectory,
        schedule: ScheduleQueries,
        ai: AiQueries,
        files: FilesViews,
        sync: SyncViews,
        clock: Clock,
        urls: UrlsSettings,
    ) -> None:
        """Store the collaborators; `urls` gives the pages the alerts point to."""
        self.identity = identity
        self.schedule = schedule
        self.ai = ai
        self.files = files
        self.sync = sync
        self.clock = clock
        self.urls = urls

    async def execute(self, actor: Actor) -> list[JsonObject]:
        """Return the `Alert` list; empty when there is nothing to do."""
        today = local_today(self.clock)
        checks = (
            self._emis_reauth,
            self._no_subgroup,
            self._files_expiring,
            self._pending_approvals,
            self._sync_failed,
        )
        alerts = [await check(actor, today) for check in checks]
        return [alert for alert in alerts if alert is not None]

    async def _emis_reauth(self, actor: Actor, today: dt.date) -> JsonObject | None:
        user = await self.identity.get_user(actor.user_id)
        if user is None or user.emis_status != "needs_reauth":
            return None
        return _alert("emis_reauth", f"{self.urls.id}/security/emis/")

    async def _no_subgroup(self, actor: Actor, today: dt.date) -> JsonObject | None:
        student = await self.schedule.get_student(actor.user_id)
        if (
            student is None
            or student.status != "active"
            or student.subgroup is not None
        ):
            return None
        return _alert(
            "no_subgroup", f"{self.urls.sp}/profile/", group_name=student.group_name
        )

    async def _files_expiring(self, actor: Actor, today: dt.date) -> JsonObject | None:
        until = today + dt.timedelta(days=FILES_WARNING_DAYS)
        dates = await self.files.expiry_dates(actor.user_id, until)
        if not dates:
            return None
        return _alert(
            "files_expiring",
            f"{self.urls.sp}/files/",
            count=len(dates),
            expires_on=dates[0].isoformat(),
        )

    async def _pending_approvals(
        self, actor: Actor, today: dt.date
    ) -> JsonObject | None:
        count = await self.ai.pending_approvals(actor.user_id)
        if count <= 0:
            return None
        return _alert("pending_approvals", f"{self.urls.sp}/assistant/", count=count)

    async def _sync_failed(self, actor: Actor, today: dt.date) -> JsonObject | None:
        failures = await self.sync.sync_failures(actor.user_id)
        if failures <= 0:
            return None
        return _alert("sync_failed", f"{self.urls.sp}/profile/", failures=failures)
