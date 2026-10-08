"""Cron schedule of the background tasks (Asia/Tashkent), read by the scheduler.

The scheduler (`python -m app scheduler`) sends each task by name, so tasks are not
imported here; a test checks that every name below is a registered task.
"""

from dataclasses import dataclass, field
from typing import Any

from taskiq.abc.schedule_source import ScheduleSource
from taskiq.scheduler.scheduled_task import ScheduledTask

TIMEZONE = "Asia/Tashkent"

# Same slots as `app.interfaces.jobs.tasks.academic.sync_all.SYNC_SLOTS`.
SYNC_SLOTS: tuple[tuple[str, str], ...] = (
    ("11:30", "30 11 * * *"),
    ("15:00", "0 15 * * *"),
    ("20:00", "0 20 * * *"),
)

EVERY_MINUTE = "* * * * *"
EVERY_5_MINUTES = "*/5 * * * *"
EVERY_10_MINUTES = "*/10 * * * *"


@dataclass(frozen=True, slots=True)
class CronJob:
    """One cron entry: task name, cron expression and fixed keyword arguments."""

    task_name: str
    cron: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def schedule_id(self) -> str:
        """Stable id (restarts of the scheduler keep the same ids)."""
        slot = self.kwargs.get("slot")
        return f"{self.task_name}@{slot}" if slot else self.task_name


CRON_JOBS: tuple[CronJob, ...] = (
    *(CronJob("academic.sync_all", cron, {"slot": slot}) for slot, cron in SYNC_SLOTS),
    CronJob("academic.generate_lessons", "0 2 * * *"),
    CronJob("academic.lesson_reminders", EVERY_MINUTE),
    CronJob("notify.dispatch_due", EVERY_MINUTE),
    CronJob("admin.start_scheduled_broadcasts", EVERY_MINUTE),
    CronJob("admin.finish_broadcasts", EVERY_5_MINUTES),
    CronJob("notify.purge_old", "30 3 * * *"),
    CronJob("files.cleanup_expired", "0 3 * * *"),
    CronJob("files.warn_expiring", "0 10 * * *"),
    CronJob("files.purge_pending", "15 * * * *"),
    CronJob("files.sweep_processing", EVERY_10_MINUTES),
    CronJob("links.flush_hits", EVERY_5_MINUTES),
    CronJob("links.release_slugs", "45 3 * * *"),
    CronJob("identity.apply_otp_resets", EVERY_10_MINUTES),
    CronJob("identity.purge_deleted_users", "0 4 * * *"),
    CronJob("mail.purge", "30 4 * * *"),
    CronJob("mail.check_bounces", "5 * * * *"),
    CronJob("mail.sweep", EVERY_10_MINUTES),
    CronJob("lms.prune_revisions", "0 5 * * *"),
    CronJob("ai.purge_admin_chats", "15 3 * * *"),
    CronJob("bootstrap.cleanup_otp_messages", EVERY_MINUTE),
)


def scheduled_tasks(jobs: tuple[CronJob, ...] = CRON_JOBS) -> list[ScheduledTask]:
    """The jobs as taskiq schedules (cron in Tashkent time)."""
    return [
        ScheduledTask(
            task_name=job.task_name,
            labels={},
            args=[],
            kwargs=dict(job.kwargs),
            schedule_id=job.schedule_id,
            cron=job.cron,
            cron_offset=TIMEZONE,
        )
        for job in jobs
    ]


class CronScheduleSource(ScheduleSource):
    """ScheduleSource that serves `CRON_JOBS`."""

    def __init__(self, jobs: tuple[CronJob, ...] = CRON_JOBS) -> None:
        """Keep the jobs (defaults to the project schedule)."""
        self._jobs = jobs

    async def get_schedules(self) -> list[ScheduledTask]:
        """Return the cron entries."""
        return scheduled_tasks(self._jobs)
