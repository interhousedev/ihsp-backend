"""Use case: alerts on the student's Today page (WEB-3)."""

import datetime as dt

from app.interfaces.http.v1.composition.ports import (
    AiClientViews,
    FilesViews,
    JsonObject,
    SyncViews,
)
from app.settings import UrlsSettings
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.identity import IdentityDirectory

# Files are deleted at the end of the term (FILE-5); warn a week ahead.
FILES_WARNING_DAYS = 7
# A seminar is a `practice` lesson (EMIS "amaliyot"); the lesson kinds are lecture,
# practice, midterm, final and other, so there is no separate seminar kind.
SEMINAR_KIND = "practice"
SEMINAR_SOON = dt.timedelta(hours=3)
# The web app hides this alert once the student dismisses it (onboarding_dismissed).
CONNECT_AI_ALERT = "connect_ai"


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
        ai_clients: AiClientViews,
        clock: Clock,
        urls: UrlsSettings,
    ) -> None:
        """Store the collaborators; `urls` gives the pages the alerts point to."""
        self.identity = identity
        self.schedule = schedule
        self.ai = ai
        self.files = files
        self.sync = sync
        self.ai_clients = ai_clients
        self.clock = clock
        self.urls = urls

    async def execute(self, actor: Actor) -> list[JsonObject]:
        """Return the `Alert` list; empty when there is nothing to do."""
        today = local_today(self.clock)
        checks = (
            self._emis_reauth,
            self._no_subgroup,
            self._seminar_soon,
            self._files_expiring,
            self._pending_approvals,
            self._sync_failed,
            self._connect_ai,
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

    async def _seminar_soon(self, actor: Actor, today: dt.date) -> JsonObject | None:
        """The next seminar (practice lesson) that starts within `SEMINAR_SOON`."""
        now = self.clock.now()
        lessons = await self.schedule.projected_lessons_for_student(
            actor.user_id, today, today + dt.timedelta(days=1)
        )
        upcoming = [
            lesson
            for lesson in lessons
            if lesson.kind == SEMINAR_KIND
            and lesson.status == "scheduled"
            and now < lesson.starts_at <= now + SEMINAR_SOON
        ]
        if not upcoming:
            return None
        lesson = min(upcoming, key=lambda item: item.starts_at)
        return _alert(
            "seminar_soon",
            f"{self.urls.sp}/schedule/",
            subject_name=lesson.subject_name,
            starts_at=lesson.starts_at.isoformat(),
            period=lesson.period,
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

    async def _connect_ai(self, actor: Actor, today: dt.date) -> JsonObject | None:
        """A student with no AI client gets the MCP setup wizard link (MCP-5)."""
        if Role.STUDENT not in actor.roles:
            return None
        if await self.ai_clients.chat_blocked(actor.user_id):
            return None
        if await self.ai_clients.has_connected_client(actor.user_id):
            return None
        return _alert(CONNECT_AI_ALERT, f"{self.urls.id}/connectors/new/")
