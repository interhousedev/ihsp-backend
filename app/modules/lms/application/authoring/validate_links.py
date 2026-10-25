"""Use cases: check the links of a course in the background and read the report."""

import asyncio
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course,
    load_course_locked,
)
from app.modules.lms.application.authoring.settings_views import (
    LinkJobView,
    LinkReportView,
    LinkResultView,
)
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.link_check import (
    FoundLink,
    LinkResult,
    extract_links,
)
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.ports.authoring.link_checker import LinkChecker
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.lms_scopes import COURSES_WRITE
from app.shared.tasks import TaskKicker

CONCURRENCY = 8
STALE_RUNNING = timedelta(minutes=10)
TASK_NAME = "lms.validate_links"


def report_view(report: dict[str, Any] | None) -> LinkReportView:
    """Convert the stored report; no report means idle."""
    if not report:
        return LinkReportView(status="idle")
    return LinkReportView.model_validate(report)


class StartLinkCheck:
    """Mark the course as being checked and enqueue the job."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, kicker: TaskKicker | None
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker

    async def execute(self, actor: Actor, course_id: UUID) -> LinkJobView:
        """Enqueue a check; a fresh running one is returned instead of a second."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT)
            access.require_scope(COURSES_WRITE)
            report = course.link_report or {}
            started = report.get("started_at")
            if (
                report.get("status") == "running"
                and started is not None
                and now < datetime.fromisoformat(started) + STALE_RUNNING
            ):
                return LinkJobView(job_id=str(report["job_id"]))
            job_id = str(uuid4())
            course.link_report = {
                "status": "running",
                "job_id": job_id,
                "started_at": now.isoformat(),
                "checked_at": None,
                "results": [],
            }
            await uow.courses.save(course)
            await uow.commit()
        if self.kicker is not None:
            await self.kicker.kick(TASK_NAME, course_id=str(course_id), job_id=job_id)
        return LinkJobView(job_id=job_id)


class GetLinkReport:
    """Return the last link report of a course."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, course_id: UUID) -> LinkReportView:
        """Return the stored report, or `idle` when none was made."""
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            (await access_to(uow, actor, course_id)).require(EDIT)
            return report_view(course.link_report)


class ValidateLinks:
    """The job: check every URL in the step drafts and store the report."""

    def __init__(
        self, uow_factory: UowFactory, checker: LinkChecker, clock: Clock
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.checker = checker
        self.clock = clock

    async def execute(self, course_id: UUID, job_id: str) -> int:
        """Check the links and save the report; return how many were checked."""
        async with self.uow_factory() as uow:
            steps = await uow.steps.list_for_course(course_id)
        links = extract_links([(str(s.id), s.title, s.draft) for s in steps])
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def one(link: FoundLink) -> LinkResult:
            async with semaphore:
                return await self.checker.check(link.url)

        results = await asyncio.gather(*(one(link) for link in links))
        views = [
            LinkResultView(
                url=link.url,
                step_id=link.step_id,
                step_title=link.step_title,
                status_code=result.status_code,
                ok=result.ok,
                error=result.error,
            ).model_dump(mode="json")
            for link, result in zip(links, results, strict=True)
        ]
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            if (course.link_report or {}).get("job_id") != job_id:
                return 0
            course.link_report = {
                "status": "done",
                "job_id": job_id,
                "checked_at": self.clock.now().isoformat(),
                "results": views,
            }
            await uow.courses.save(course)
            await uow.commit()
        return len(views)
