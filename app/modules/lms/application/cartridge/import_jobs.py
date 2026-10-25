"""Starting, running and following a cartridge import job.

The HTTP request stores the upload as a temporary file and kicks
``lms.import_cartridge``; the worker runs `ImportCartridge` as a tracked job (it
shows in the admin Processes list and can be stopped there) and stores the result
for the uploader, who polls `GetCartridgeImport`.
"""

from dataclasses import asdict
from typing import Any, Final
from uuid import UUID

from app.modules.lms.application.cartridge.import_cartridge import ImportCartridge
from app.modules.lms.domain.authoring.errors import CoursePermissionError
from app.modules.lms.domain.cartridge.archive import MAX_ARCHIVE_BYTES
from app.modules.lms.domain.cartridge.errors import (
    CartridgeImportNotFoundError,
    CartridgeInvalidError,
)
from app.modules.lms.ports.cartridge_reports import CartridgeImportResults
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.jobs import JobTracker, enqueue, run_job
from app.shared.lms_scopes import COURSES_WRITE, scope_allows
from app.shared.tasks import TaskKicker

import structlog

JOB_KIND: Final = "lms_cartridge_import"
TASK_NAME: Final = "lms.import_cartridge"
log = structlog.get_logger(__name__)


class StartCartridgeImport:
    """Keep the upload for a day and queue the import."""

    def __init__(
        self, files: FilesApi, kicker: TaskKicker, tracker: JobTracker
    ) -> None:
        """Store collaborators."""
        self.files = files
        self.kicker = kicker
        self.tracker = tracker

    async def execute(self, actor: Actor, *, name: str, data: bytes) -> str:
        """Return the job ID.

        Raises:
            ForbiddenError: Neither an LMS admin nor a course creator.
            CartridgeInvalidError: Too large, or not a zip archive.
        """
        actor.require(Role.LMS_ADMIN, Role.LMS_CREATOR)
        if not scope_allows(actor.scopes, COURSES_WRITE):
            raise CoursePermissionError(params={"permission": COURSES_WRITE})
        if len(data) > MAX_ARCHIVE_BYTES:
            raise CartridgeInvalidError(
                params={"reason": "too-large", "max_bytes": MAX_ARCHIVE_BYTES}
            )
        if not data.startswith(b"PK"):
            raise CartridgeInvalidError(params={"reason": "not-zip"})
        upload = await self.files.store_bytes(
            owner_id=actor.user_id,
            scope=FileScope.STAFF,
            purpose=FilePurpose.LINK,
            name=(name or "course.imscc")[:200],
            data=data,
            expires_days=1,
        )
        job_id = await enqueue(
            self.tracker,
            JOB_KIND,
            f"Cartridge import: {name[:100]}",
            started_by=str(actor.user_id),
        )
        await self.kicker.kick(
            TASK_NAME,
            job_id=job_id,
            file_id=str(upload.id),
            user_id=str(actor.user_id),
            roles=sorted(r.value for r in actor.roles),
            scopes=sorted(actor.scopes),
        )
        return job_id


class RunCartridgeImport:
    """The worker side: run the import as a job and keep its result."""

    def __init__(
        self,
        files: FilesApi,
        tracker: JobTracker,
        results: CartridgeImportResults,
        importer: ImportCartridge,
    ) -> None:
        """Store collaborators."""
        self.files = files
        self.tracker = tracker
        self.results = results
        self.importer = importer

    async def execute(self, *, job_id: str, file_id: UUID, actor: Actor) -> None:
        """Import; a broken cartridge ends the job as failed with its reason."""
        try:
            async with run_job(
                self.tracker, JOB_KIND, "Cartridge import", job_id=job_id
            ) as job:
                if job is None:
                    return
                data = await self.files.read_bytes(file_id)
                try:
                    outcome = await self.importer.execute(actor, data)
                except BaseError as exc:
                    await self.results.save(
                        job_id, {"error": str(exc.params.get("reason") or exc.code)}
                    )
                    raise
                await self.results.save(
                    job_id,
                    {
                        "course_id": str(outcome.course_id),
                        "report": asdict(outcome.report),
                    },
                )
        except BaseError as exc:
            log.info("lms_cartridge_import_failed", job_id=job_id, code=exc.code)
        finally:
            await self.files.delete_file(file_id)


class GetCartridgeImport:
    """What the uploader sees while polling."""

    def __init__(self, tracker: JobTracker, results: CartridgeImportResults) -> None:
        """Store collaborators."""
        self.tracker = tracker
        self.results = results

    async def execute(self, actor: Actor, job_id: str) -> dict[str, Any]:
        """Return status, progress, the new course and the report.

        Raises:
            CartridgeImportNotFoundError: Unknown, expired or someone else's job.
        """
        job = await self.tracker.get(job_id)
        if job is None or job.kind != JOB_KIND or job.started_by != str(actor.user_id):
            raise CartridgeImportNotFoundError(params={"job_id": job_id})
        result = await self.results.get(job_id) or {}
        error = result.get("error")
        if job.status == "failed" and not error:
            error = "internal"
        return {
            "job_id": job.id,
            "status": job.status,
            "done": job.done,
            "total": job.total,
            "course_id": result.get("course_id"),
            "error": error,
            "report": result.get("report"),
        }
