"""Data exports: request, list, download, build, clean up."""

import io
import json
import logging
import zipfile
from collections.abc import Sequence
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import UUID

from app.modules.files.ports.storage import ObjectStorage
from app.modules.privacy.domain.errors import (
    ExportNotFoundError,
    ExportRateLimitedError,
)
from app.modules.privacy.domain.models import (
    EXPORT_INTERVAL_HOURS,
    EXPORT_VALID_DAYS,
    ExportJob,
    ExportStatus,
)
from app.modules.privacy.ports.gateways import OwnedFiles
from app.modules.privacy.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.privacy import AccountControl
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from app.shared.personal_data import PersonalData
from app.shared.tasks import TaskKicker

logger = logging.getLogger(__name__)

ARCHIVE_TYPE = "application/zip"
FILES_BYTES_LIMIT = 256 * 1024 * 1024  # uploads beyond this are listed, not packed
CLEANUP_BATCH = 200
LIST_LIMIT = 20


class RequestExport:
    """The user asks for a copy of their data (one per 24 hours)."""

    def __init__(
        self, *, uow_factory: UowFactory, kicker: TaskKicker, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._kicker = kicker
        self._clock = clock

    async def execute(self, user_id: UUID) -> ExportJob:
        """Queue an export and start ``privacy.build_export``.

        Raises:
            ExportRateLimitedError: The last export is younger than 24 hours.
        """
        now = self._clock.now()
        async with self._uow_factory() as uow:
            last = await uow.exports.latest_of(user_id)
            if last is not None:
                wait = last.created_at + timedelta(hours=EXPORT_INTERVAL_HOURS) - now
                if wait > timedelta(0):
                    raise ExportRateLimitedError(
                        params={"retry_after": int(wait.total_seconds()) + 1}
                    )
            job = ExportJob(new_id(), user_id, ExportStatus.QUEUED, now)
            await uow.exports.add(job)
            uow.after_commit(
                partial(
                    self._kicker.kick, "privacy.build_export", export_id=str(job.id)
                )
            )
            await uow.commit()
            return job


class ListExports:
    """The caller's recent exports."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, user_id: UUID) -> Sequence[ExportJob]:
        """Newest first."""
        async with self._uow_factory() as uow:
            return await uow.exports.list_of(user_id, limit=LIST_LIMIT)


class DownloadExport:
    """A short-lived link to the archive of the caller's own export."""

    def __init__(
        self, *, uow_factory: UowFactory, storage: ObjectStorage, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._clock = clock

    async def execute(self, user_id: UUID, export_id: UUID) -> str:
        """Return the presigned URL.

        Raises:
            ExportNotFoundError: Not the caller's, not ready or expired.
        """
        async with self._uow_factory() as uow:
            job = await uow.exports.get(export_id)
        if (
            job is None
            or job.user_id != user_id
            or not job.is_downloadable(self._clock.now())
            or job.storage_key is None
        ):
            raise ExportNotFoundError
        return await self._storage.presign_get(
            job.storage_key,
            filename="my-data.zip",
            inline=False,
            content_type=ARCHIVE_TYPE,
            expires=60,
        )


def _json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode()


class BuildExport:
    """Task body: pack every module's rows and the user's files into a ZIP."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        sources: Sequence[PersonalData],
        files: OwnedFiles,
        storage: ObjectStorage,
        accounts: AccountControl,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._sources = sources
        self._files = files
        self._storage = storage
        self._accounts = accounts
        self._clock = clock

    async def execute(self, export_id: UUID) -> bool:
        """Build and store the archive; return False when there was nothing to do."""
        async with self._uow_factory() as uow:
            job = await uow.exports.get(export_id)
            if job is None or job.status is not ExportStatus.QUEUED:
                return False
            job.status = ExportStatus.RUNNING
            await uow.exports.save(job)
            await uow.commit()
        try:
            data = await self._pack(job.user_id)
            key = f"privacy/exports/{job.user_id}/{job.id}.zip"
            await self._storage.put(key, data, ARCHIVE_TYPE)
        except Exception as exc:
            logger.exception("export %s failed", export_id)
            await self._finish(job, ExportStatus.FAILED, error=type(exc).__name__)
            return False
        now = self._clock.now()
        expires = now + timedelta(days=EXPORT_VALID_DAYS)
        await self._finish(
            job, ExportStatus.READY, key=key, size=len(data), expires=expires
        )
        await self._accounts.send_notice(
            job.user_id,
            "privacy-mail-export-ready",
            {"expires": expires.date().isoformat()},
        )
        return True

    async def _finish(
        self,
        job: ExportJob,
        status: ExportStatus,
        *,
        key: str | None = None,
        size: int | None = None,
        expires: Any = None,
        error: str | None = None,
    ) -> None:
        async with self._uow_factory() as uow:
            job.status = status
            job.finished_at = self._clock.now()
            job.storage_key, job.byte_size = key, size
            job.expires_at, job.error = expires, error
            await uow.exports.save(job)
            if status is ExportStatus.READY:
                uow.notify(
                    NotificationDraft(
                        user_id=job.user_id,
                        type=NotificationType.PRIVACY_UPDATE,
                        payload={
                            "kind": "export_ready",
                            "export_id": str(job.id),
                            "expires_at": expires.isoformat(),
                        },
                        dedupe_key=f"privacy:{job.id}:export_ready",
                    )
                )
            await uow.commit()

    async def _pack(self, user_id: UUID) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            tables: dict[str, list[dict[str, Any]]] = {}
            for source in self._sources:
                tables.update(await source.export(user_id))
            for name, rows in sorted(tables.items()):
                if rows:
                    archive.writestr(f"data/{name}.json", _json(rows))
            skipped: list[dict[str, Any]] = []
            packed = 0
            for index, item in enumerate(await self._files.list_of(user_id)):
                if packed + item.byte_size > FILES_BYTES_LIMIT:
                    skipped.append({"name": item.name, "byte_size": item.byte_size})
                    continue
                body = await self._storage.get(item.key)
                packed += len(body)
                archive.writestr(f"files/{index:04d}-{_safe(item.name)}", body)
            if skipped:
                archive.writestr("files/not-included.json", _json(skipped))
        return buffer.getvalue()


def _safe(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return cleaned.strip(".") or "file"


class CleanupExports:
    """Cron body: delete the archives whose link expired."""

    def __init__(
        self, *, uow_factory: UowFactory, storage: ObjectStorage, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._clock = clock

    async def execute(self) -> int:
        """Delete a batch of expired archives; return how many."""
        async with self._uow_factory() as uow:
            jobs = await uow.exports.expired(self._clock.now(), limit=CLEANUP_BATCH)
            keys = [j.storage_key for j in jobs if j.storage_key]
            await self._storage.delete_many(keys)
            for job in jobs:
                job.storage_key = None
                await uow.exports.save(job)
            await uow.commit()
            return len(jobs)
